from datetime import date, datetime, time, timedelta

import pytest

from medremind.core.models import DoseStatus, Frequency, Medication
from medremind.core.services.medications import ValidationError


def add(c, name="Aspirina", times=(time(8, 0), time(20, 0)), **kw):
    return c.meds.save(Medication(name, "81mg", times=list(times), stock_units=10, start_date=date(2026, 10, 1), **kw))


def test_status_depends_on_time_window(c, clock):
    add(c)
    doses = c.schedule.today()
    assert [d.status for d in doses] == [DoseStatus.MISSED, DoseStatus.UPCOMING]  # 12:30
    clock.set(2026, 10, 14, 19, 45)
    assert c.schedule.today()[1].status == DoseStatus.DUE


def test_mark_taken_decrements_stock_once_and_undo_restores(c):
    m = add(c)
    at = datetime(2026, 10, 14, 8, 0)
    c.schedule.mark_taken(m.id, at)
    c.schedule.mark_taken(m.id, at)  # repetido não desconta de novo
    assert c.meds.get(m.id).stock_units == 9
    assert c.schedule.today()[0].status == DoseStatus.TAKEN
    c.schedule.undo(m.id, at)
    assert c.meds.get(m.id).stock_units == 10
    assert c.schedule.today()[0].status == DoseStatus.MISSED


def test_snooze_then_due_again(c, clock):
    m = add(c, times=[time(12, 30)])
    c.schedule.snooze(m.id, datetime(2026, 10, 14, 12, 30), 10)
    assert c.schedule.today()[0].status == DoseStatus.SNOOZED
    clock.set(2026, 10, 14, 12, 41)
    assert c.schedule.today()[0].status == DoseStatus.DUE


def test_weekdays_and_paused(c):
    add(c, "Vitamina D", times=[time(8, 0)], frequency=Frequency.WEEKDAYS, weekdays=[0, 4])  # seg e sex
    assert c.schedule.today() == []  # quarta
    assert len(c.schedule.doses_for_day(date(2026, 10, 16))) == 1  # sexta
    m = add(c, "Outro", times=[time(9, 0)])
    c.meds.set_paused(m.id, True)
    assert c.schedule.doses_for_day(date(2026, 10, 16))[0].medication.name == "Vitamina D"


def test_adherence_and_streak(c, clock):
    m = add(c, times=[time(8, 0)])
    for day in range(1, 14):  # 1 a 13/10
        if day != 5:
            c.schedule.mark_taken(m.id, datetime(2026, 10, day, 8, 0), datetime(2026, 10, day, 8, 20))
    a = c.schedule.adherence(date(2026, 10, 1), date(2026, 10, 14))
    assert (a.due, a.taken) == (14, 12)  # hoje 08:00 já passou da janela -> perdida
    assert a.on_time == 12
    assert c.schedule.streak() == 8  # 6 a 13/10; hoje incompleto não quebra a sequência


def test_next_dose_prefers_due(c, clock):
    add(c, "A", times=[time(12, 45)])
    add(c, "B", times=[time(18, 0)])
    assert c.schedule.next_dose().medication.name == "A"


@pytest.mark.parametrize("kwargs,msg", [
    ({"name": ""}, "nome"),
    ({"times": []}, "horário"),
    ({"times": [time(8, 0), time(8, 0)]}, "repetidos"),
    ({"frequency": Frequency.WEEKDAYS, "weekdays": []}, "dia da semana"),
    ({"dose_units": 0}, "maior que zero"),
])
def test_validation(c, kwargs, msg):
    base = {"name": "X", "times": [time(8, 0)]}
    base.update(kwargs)
    with pytest.raises(ValidationError, match=msg):
        c.meds.save(Medication(**base))


def test_stock_forecast(c):
    m = add(c, times=[time(8, 0), time(20, 0)], refill_alert_days=7)  # 10 unidades, 2/dia
    s = c.meds.stock_status(c.meds.get(m.id))
    assert s.days_left == 5 and s.low and s.runs_out_on == date(2026, 10, 14) + timedelta(days=5)
    c.meds.refill(m.id, 30)
    assert not c.meds.stock_status(c.meds.get(m.id)).low


def test_dose_text_units(c):
    from medremind.core.models import MedForm
    assert Medication("X", form=MedForm.GOTAS, dose_units=20).dose_text == "20 gotas"
    assert Medication("X", dose_units=1).dose_text == "1 comprimido"

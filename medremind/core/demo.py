"""Dados de demonstração (os mesmos do protótipo do Stitch)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .container import Container
from .models import Contact, DoseLog, DoseStatus, Frequency, Medication, MedForm, Profile, WaterLog


def seed_demo(c: Container, today: date | None = None) -> None:
    if c.meds.list():
        return
    today = today or c.schedule.clock().date()
    start = today - timedelta(days=27)

    c.settings.save_profile(Profile(
        name="Sarah Jenkins", birth_date=date(1982, 3, 15), email="sarah.j@example.com",
        health_id="MR-84729-SJ", blood_type="O+", allergies="Penicilina (exemplo)",
        conditions="Hipertensão (exemplo)", pharmacy_name="Farmácia Cornerstone",
        pharmacy_address="Rua Principal, 124", water_goal_ml=2000,
    ))
    c.contacts.add(Contact("Michael Jenkins", "Cônjuge", "+55 11 90000-0001"))
    c.contacts.add(Contact("Dra. Emily Chen", "Clínica geral", "+55 11 90000-0002", is_doctor=True))

    meds = [
        Medication("Lisinopril", "10mg", MedForm.COMPRIMIDO, 1, Frequency.DAILY, [time(8, 0)],
                   instructions="Em jejum", start_date=start, stock_units=4, stock_total=90),
        Medication("Aspirina", "81mg", MedForm.COMPRIMIDO, 1, Frequency.DAILY, [time(13, 0)],
                   instructions="Tomar com comida", start_date=start, stock_units=74, stock_total=100),
        Medication("Atorvastatina", "40mg", MedForm.COMPRIMIDO, 1, Frequency.DAILY, [time(20, 0)],
                   instructions="Antes de dormir", start_date=start, stock_units=56, stock_total=60),
        Medication("Vitamina D3", "2000 UI", MedForm.CAPSULA, 1, Frequency.WEEKDAYS, [time(8, 0)],
                   weekdays=[0, 2, 4], start_date=start, stock_units=20, stock_total=30),
        Medication("Dipirona", "500mg", MedForm.GOTAS, 1, Frequency.AS_NEEDED, [],
                   instructions="Se tiver dor ou febre", start_date=start, track_stock=False),
    ]
    for m in meds:
        c.meds.repo.add(m)

    # Histórico realista: ~90% de adesão, com algumas falhas determinísticas.
    logs = c.schedule.logs
    now = c.schedule.clock()
    day = start
    i = 0
    while day < today:
        for m in meds:
            if not m.is_scheduled_on(day):
                continue
            for t in m.times:
                at = datetime.combine(day, t)
                i += 1
                if i % 11 == 0:
                    continue  # perdida
                if i % 17 == 0:
                    logs.upsert(DoseLog(m.id, at, DoseStatus.SKIPPED, acted_at=at))
                    continue
                late = timedelta(minutes=(i * 7) % 50)
                logs.upsert(DoseLog(m.id, at, DoseStatus.TAKEN, acted_at=at + late))
        day += timedelta(days=1)
    # Hoje: o que já passou foi tomado.
    for m in meds:
        if m.is_scheduled_on(today):
            for t in m.times:
                at = datetime.combine(today, t)
                if at + timedelta(minutes=30) < now:
                    logs.upsert(DoseLog(m.id, at, DoseStatus.TAKEN, acted_at=at + timedelta(minutes=10)))

    for hh, mm, ml, kind in [(8, 0, 200, "copo"), (10, 30, 500, "garrafa")]:
        at = datetime.combine(today, time(hh, mm))
        if at <= now:
            c.hydration.repo.add(WaterLog(ml, at, kind))
    c.audit.log("app_aberto", "dados de demonstração carregados")

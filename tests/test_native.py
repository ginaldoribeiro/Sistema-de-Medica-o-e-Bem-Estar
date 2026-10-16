"""Plano de lembretes do sistema e comportamento dos recursos nativos fora do celular."""
from __future__ import annotations

import asyncio
from datetime import datetime, time

import flet as ft

from medremind.core.models import Frequency, Medication
from medremind.core.services.notification_plan import plan, stable_id
from medremind.ui.native import Native


def test_plan_lists_future_doses_with_stable_ids(c, clock):
    c.meds.save(Medication("Aspirina", "81mg", times=[time(8, 0), time(20, 0)], instructions="com comida"))
    c.meds.save(Medication("Sem lembrete", times=[time(21, 0)], reminders=False))
    c.meds.save(Medication("Dipirona", frequency=Frequency.AS_NEEDED))
    items = plan(c.schedule)  # agora: 14/10 12:30, horizonte de 48 h
    assert [r.at for r in items] == [datetime(2026, 10, 14, 20), datetime(2026, 10, 15, 8), datetime(2026, 10, 15, 20),
                                     datetime(2026, 10, 16, 8)]
    assert items[0].title == "Hora de tomar Aspirina 81mg" and "com comida" in items[0].body
    assert items == plan(c.schedule)  # reagendar não muda ids
    assert len({r.id for r in items}) == 4 and all(0 < r.id < 2 ** 31 for r in items)


def test_plan_skips_taken_follows_snooze_and_can_hide_names(c, clock):
    m = c.meds.save(Medication("Losartana", "50mg", times=[time(13, 0), time(18, 0)]))
    c.schedule.mark_taken(m.id, datetime(2026, 10, 14, 13, 0))
    clock.set(2026, 10, 14, 18, 5)
    c.schedule.snooze(m.id, datetime(2026, 10, 14, 18, 0), 10)
    items = plan(c.schedule, horizon_hours=12, hide_names=True)
    assert items[0].at == datetime(2026, 10, 14, 18, 15)          # segue o adiamento
    assert items[0].title == "Hora de tomar seu remédio"          # nome oculto na tela bloqueada
    assert all(r.at.date() == datetime(2026, 10, 14).date() or r.at.hour == 13 for r in items)
    assert plan(c.schedule, horizon_hours=12, limit=1, hide_names=True) == items[:1]


def test_stable_id_is_deterministic():
    assert stable_id("1@2026-10-14T08:00") == stable_id("1@2026-10-14T08:00") != stable_id("1@2026-10-14T20:00")


class _FakePage:
    def __init__(self, platform, web=False):
        self.platform = platform
        self.web = web


def test_native_is_quietly_unavailable_on_web_and_linux():
    for page in (_FakePage(ft.PagePlatform.LINUX), _FakePage(ft.PagePlatform.ANDROID, web=True)):
        n = Native(page)
        assert asyncio.run(n.biometrics_available()) is False
        assert asyncio.run(n.authenticate()) is False
        assert n.can_schedule is False
        assert asyncio.run(n.schedule([])) == 0

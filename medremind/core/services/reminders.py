"""Motor de lembretes.

A interface chama ``poll()`` periodicamente (ex.: a cada 30 s). O motor devolve
as doses que acabaram de entrar no horário e ainda não foram avisadas; com o
"alerta persistente" ligado, reavisa a cada ``repeat_minutes`` até o usuário agir.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from ..models import DoseStatus, PlannedDose
from ..repositories import SettingsRepository
from .schedule import ScheduleService

DEFAULT_PREFS = {"sound": True, "vibration": True, "persistent": False, "repeat_minutes": 5}


@dataclass
class Reminder:
    dose: PlannedDose
    repeat: bool  # True quando é um reaviso do alerta persistente


class ReminderEngine:
    def __init__(self, schedule: ScheduleService, settings: SettingsRepository,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.schedule = schedule
        self.settings = settings
        self.clock = clock
        self._notified: dict[str, datetime] = {}

    def prefs(self) -> dict:
        return {**DEFAULT_PREFS, **(self.settings.get("notifications", {}) or {})}

    def save_prefs(self, **changes) -> dict:
        prefs = {**self.prefs(), **changes}
        self.settings.set("notifications", prefs)
        return prefs

    def poll(self) -> list[Reminder]:
        now = self.clock()
        prefs = self.prefs()
        out: list[Reminder] = []
        for dose in self.schedule.today():
            if dose.status != DoseStatus.DUE or not dose.medication.reminders:
                continue
            # Avisamos a partir do horário (ou do fim do adiamento), não 30 min antes.
            start = dose.snoozed_until or dose.scheduled_at
            if now < start:
                continue
            key = dose.key + (f"/{dose.snoozed_until:%H%M}" if dose.snoozed_until else "")
            last = self._notified.get(key)
            if last is None:
                self._notified[key] = now
                out.append(Reminder(dose, repeat=False))
            elif prefs["persistent"] and now - last >= timedelta(minutes=prefs["repeat_minutes"]):
                self._notified[key] = now
                out.append(Reminder(dose, repeat=True))
        return out

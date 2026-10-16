"""Plano de lembretes para o sistema operacional agendar (app fechado).

Gera as próximas doses dentro de um horizonte, com ids estáveis: reagendar a
mesma lista não duplica avisos. O iOS aceita no máximo 64 avisos pendentes, por
isso há um limite.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import DoseStatus
from .schedule import ScheduleService

MAX_PENDING = 60
HORIZON_HOURS = 48


@dataclass(frozen=True)
class PlannedReminder:
    id: int
    title: str
    body: str
    at: datetime
    payload: str


def stable_id(key: str) -> int:
    """Inteiro positivo de 31 bits estável entre execuções (o Android exige int32)."""
    return zlib.crc32(key.encode()) & 0x7FFFFFFF


def plan(schedule: ScheduleService, now: datetime | None = None, horizon_hours: int = HORIZON_HOURS,
         limit: int = MAX_PENDING, hide_names: bool = False) -> list[PlannedReminder]:
    """Doses futuras ainda não registradas, em ordem, até ``limit``.

    ``hide_names`` troca o nome do remédio por um texto neutro — útil para quem
    não quer o nome do medicamento aparecendo na tela bloqueada.
    """
    now = now or schedule.clock()
    end = now + timedelta(hours=horizon_hours)
    out: list[PlannedReminder] = []
    day = now.date()
    while datetime.combine(day, datetime.min.time()) <= end and len(out) < limit:
        for d in schedule.doses_for_day(day):
            if not d.medication.reminders:
                continue
            at = d.snoozed_until or d.scheduled_at
            if d.status not in (DoseStatus.UPCOMING, DoseStatus.DUE, DoseStatus.SNOOZED) or not (now < at <= end):
                continue
            name = "seu remédio" if hide_names else d.medication.display_name
            body = f"{d.medication.dose_text}" + (f" · {d.medication.instructions}" if d.medication.instructions
                                                   and not hide_names else "")
            out.append(PlannedReminder(id=stable_id(d.key), title=f"Hora de tomar {name}", body=body, at=at,
                                       payload=d.key))
        day += timedelta(days=1)
    out.sort(key=lambda r: r.at)
    return out[:limit]

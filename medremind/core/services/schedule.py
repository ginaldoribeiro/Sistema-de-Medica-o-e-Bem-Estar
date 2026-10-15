"""Agenda de doses, registro (tomar / pular / adiar) e métricas de adesão."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from ..models import DoseLog, DoseStatus, Medication, PlannedDose
from ..repositories import DoseLogRepository, MedicationRepository
from .audit import AuditService

Clock = Callable[[], datetime]

# Janela em que uma dose é considerada "agora" (antes e depois do horário).
DUE_BEFORE = timedelta(minutes=30)
# Depois deste tempo sem registro a dose conta como perdida.
GRACE_AFTER = timedelta(hours=2)
# Tolerância para considerar a dose tomada "no horário".
ON_TIME = timedelta(minutes=60)


@dataclass
class DaySummary:
    day: date
    planned: int
    taken: int
    missed: int
    skipped: int
    pending: int

    @property
    def complete(self) -> bool:
        return self.planned > 0 and self.taken == self.planned

    @property
    def state(self) -> str:
        """Estado para o calendário semanal: done | partial | missed | pending | empty."""
        if self.planned == 0:
            return "empty"
        if self.pending and not (self.missed or self.skipped):
            return "pending"
        if self.complete:
            return "done"
        if self.taken == 0 and not self.pending:
            return "missed"
        return "partial"


@dataclass
class Adherence:
    due: int        # doses que já deveriam ter sido tomadas
    taken: int
    on_time: int

    @property
    def rate(self) -> float:
        return self.taken / self.due if self.due else 1.0

    @property
    def on_time_rate(self) -> float:
        return self.on_time / self.due if self.due else 1.0


class ScheduleService:
    def __init__(self, meds: MedicationRepository, logs: DoseLogRepository,
                 audit: AuditService, clock: Clock = datetime.now) -> None:
        self.meds = meds
        self.logs = logs
        self.audit = audit
        self.clock = clock

    # ------------------------------------------------------------------ agenda
    def _status(self, scheduled_at: datetime, log: DoseLog | None, now: datetime) -> DoseStatus:
        if log is not None:
            if log.status == DoseStatus.SNOOZED:
                if log.snoozed_until and now >= log.snoozed_until:
                    return DoseStatus.DUE
                return DoseStatus.SNOOZED
            return log.status
        if now < scheduled_at - DUE_BEFORE:
            return DoseStatus.UPCOMING
        if now <= scheduled_at + GRACE_AFTER:
            return DoseStatus.DUE
        return DoseStatus.MISSED

    def doses_for_day(self, day: date, meds: list[Medication] | None = None) -> list[PlannedDose]:
        now = self.clock()
        meds = meds if meds is not None else self.meds.list(include_paused=False)
        start = datetime.combine(day, datetime.min.time())
        logs = {(l.medication_id, l.scheduled_at): l for l in self.logs.between(start, start + timedelta(days=1))}
        out: list[PlannedDose] = []
        for med in meds:
            if not med.is_scheduled_on(day):
                continue
            for t in med.times:
                at = datetime.combine(day, t)
                log = logs.get((med.id, at))
                out.append(PlannedDose(
                    medication=med,
                    scheduled_at=at,
                    status=self._status(at, log, now),
                    acted_at=log.acted_at if log else None,
                    snoozed_until=log.snoozed_until if log else None,
                ))
        out.sort(key=lambda d: (d.scheduled_at, d.medication.name))
        return out

    def today(self) -> list[PlannedDose]:
        return self.doses_for_day(self.clock().date())

    def next_dose(self) -> PlannedDose | None:
        """A próxima dose que pede ação: primeiro as que estão no horário, depois as futuras."""
        now = self.clock()
        for offset in range(0, 3):
            doses = self.doses_for_day(now.date() + timedelta(days=offset))
            actionable = [d for d in doses if d.status in (DoseStatus.DUE, DoseStatus.SNOOZED, DoseStatus.UPCOMING)]
            due = [d for d in actionable if d.status == DoseStatus.DUE]
            if due:
                return due[0]
            if actionable:
                return min(actionable, key=lambda d: d.snoozed_until or d.scheduled_at)
        return None

    # --------------------------------------------------------------- registros
    def _require_med(self, med_id: int) -> Medication:
        med = self.meds.get(med_id)
        if med is None:
            raise ValueError(f"Medicação {med_id} não encontrada")
        return med

    def mark_taken(self, med_id: int, scheduled_at: datetime, at: datetime | None = None) -> None:
        med = self._require_med(med_id)
        previous = self.logs.get(med_id, scheduled_at)
        self.logs.upsert(DoseLog(med_id, scheduled_at, DoseStatus.TAKEN, acted_at=at or self.clock()))
        if med.track_stock and (previous is None or previous.status != DoseStatus.TAKEN):
            self.meds.adjust_stock(med_id, -med.dose_units)
        self.audit.log("dose_tomada", f"{med.display_name} ({scheduled_at:%d/%m %H:%M})")

    def take_as_needed(self, med_id: int) -> None:
        """Registra uma dose avulsa (remédio 'conforme necessário')."""
        now = self.clock().replace(second=0, microsecond=0)
        self.mark_taken(med_id, now, now)

    def skip(self, med_id: int, scheduled_at: datetime, note: str = "") -> None:
        med = self._require_med(med_id)
        self._undo_stock_if_taken(med, scheduled_at)
        self.logs.upsert(DoseLog(med_id, scheduled_at, DoseStatus.SKIPPED, acted_at=self.clock(), note=note))
        self.audit.log("dose_pulada", f"{med.display_name} ({scheduled_at:%d/%m %H:%M})")

    def snooze(self, med_id: int, scheduled_at: datetime, minutes: int = 10) -> datetime:
        med = self._require_med(med_id)
        until = self.clock() + timedelta(minutes=minutes)
        self.logs.upsert(DoseLog(med_id, scheduled_at, DoseStatus.SNOOZED, snoozed_until=until))
        self.audit.log("dose_adiada", f"{med.display_name} por {minutes} min")
        return until

    def undo(self, med_id: int, scheduled_at: datetime) -> None:
        med = self._require_med(med_id)
        self._undo_stock_if_taken(med, scheduled_at)
        self.logs.delete(med_id, scheduled_at)
        self.audit.log("registro_desfeito", f"{med.display_name} ({scheduled_at:%d/%m %H:%M})")

    def _undo_stock_if_taken(self, med: Medication, scheduled_at: datetime) -> None:
        previous = self.logs.get(med.id, scheduled_at)
        if previous and previous.status == DoseStatus.TAKEN and med.track_stock:
            self.meds.adjust_stock(med.id, med.dose_units)

    # ---------------------------------------------------------------- métricas
    def day_summary(self, day: date) -> DaySummary:
        doses = self.doses_for_day(day)
        count = lambda *st: sum(1 for d in doses if d.status in st)  # noqa: E731
        return DaySummary(
            day=day,
            planned=len(doses),
            taken=count(DoseStatus.TAKEN),
            missed=count(DoseStatus.MISSED),
            skipped=count(DoseStatus.SKIPPED),
            pending=count(DoseStatus.DUE, DoseStatus.SNOOZED, DoseStatus.UPCOMING),
        )

    def week(self, reference: date | None = None) -> list[DaySummary]:
        """Segunda a domingo da semana de ``reference``."""
        ref = reference or self.clock().date()
        monday = ref - timedelta(days=ref.weekday())
        return [self.day_summary(monday + timedelta(days=i)) for i in range(7)]

    def adherence(self, start: date, end: date) -> Adherence:
        """Adesão entre ``start`` e ``end`` (inclusive), contando só doses já vencidas."""
        meds = self.meds.list(include_paused=True)
        due = taken = on_time = 0
        day = start
        while day <= end:
            for d in self.doses_for_day(day, meds=[m for m in meds if not m.paused]):
                if d.status in (DoseStatus.UPCOMING, DoseStatus.DUE, DoseStatus.SNOOZED):
                    continue
                due += 1
                if d.status == DoseStatus.TAKEN:
                    taken += 1
                    if d.acted_at and abs(d.acted_at - d.scheduled_at) <= ON_TIME:
                        on_time += 1
            day += timedelta(days=1)
        return Adherence(due=due, taken=taken, on_time=on_time)

    def weekly_adherence(self, weeks: int = 4) -> list[tuple[date, float | None]]:
        """Adesão das últimas ``weeks`` semanas (a última é a atual). None = sem doses."""
        today = self.clock().date()
        monday = today - timedelta(days=today.weekday())
        out = []
        for i in range(weeks - 1, -1, -1):
            start = monday - timedelta(weeks=i)
            end = min(start + timedelta(days=6), today)
            a = self.adherence(start, end)
            out.append((start, a.rate if a.due else None))
        return out

    def streak(self) -> int:
        """Dias seguidos com todas as doses tomadas (hoje conta se já estiver completo)."""
        today = self.clock().date()
        days = 0
        summary = self.day_summary(today)
        if summary.complete:
            days += 1
        day = today - timedelta(days=1)
        for _ in range(365):
            s = self.day_summary(day)
            if s.planned == 0:
                day -= timedelta(days=1)
                continue
            if not s.complete:
                break
            days += 1
            day -= timedelta(days=1)
        return days

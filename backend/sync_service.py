"""Lado servidor da sincronização (ver ``medremind/core/sync.py`` para o protocolo)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from medremind.core.models import DoseStatus, Frequency, MedForm
from medremind.core.sync import KINDS

from . import orm
from .adapters import bump

MODELS = {"medications": orm.Medication, "dose_logs": orm.DoseLog, "water_logs": orm.WaterLog,
          "contacts": orm.Contact}


def _dt(v):
    return datetime.fromisoformat(v) if v else None


def _d(v):
    return date.fromisoformat(v) if v else None


def _validate(kind: str, item: dict) -> str | None:
    """Validação mínima de entrada — o servidor nunca confia no cliente."""
    if not isinstance(item.get("uuid"), str) or not 8 <= len(item["uuid"]) <= 32:
        return "uuid inválido"
    if not isinstance(item.get("updated_at"), str):
        return "updated_at ausente"
    try:
        if kind == "medications":
            MedForm(item["form"])
            Frequency(item["frequency"])
            if not str(item.get("name", "")).strip():
                return "nome vazio"
            [datetime.strptime(t, "%H:%M") for t in item.get("times", [])]
        elif kind == "dose_logs":
            DoseStatus(item["status"])
            datetime.fromisoformat(item["scheduled_at"])
        elif kind == "water_logs":
            if not 0 < int(item["amount_ml"]) <= 3000:
                return "quantidade inválida"
            datetime.fromisoformat(item["logged_at"])
        elif kind == "contacts" and not str(item.get("name", "")).strip():
            return "nome vazio"
    except (KeyError, ValueError, TypeError) as exc:
        return f"campo inválido: {exc}"
    return None


def _assign(kind: str, row, item: dict) -> None:
    if kind == "medications":
        row.name, row.strength = item["name"][:80], (item.get("strength") or "")[:40]
        row.form, row.frequency = item["form"], item["frequency"]
        row.dose_units = float(item.get("dose_units", 1))
        row.times = ",".join(sorted(item.get("times", [])))
        row.weekdays = ",".join(str(w) for w in sorted(set(item.get("weekdays", []))))
        row.instructions = item.get("instructions") or ""
        row.start_date, row.end_date = _d(item.get("start_date")), _d(item.get("end_date"))
        row.track_stock, row.reminders, row.paused = bool(item.get("track_stock")), bool(item.get("reminders")), \
            bool(item.get("paused"))
        row.stock_units, row.stock_total = float(item.get("stock_units", 0)), float(item.get("stock_total", 0))
        row.refill_alert_days = int(item.get("refill_alert_days", 7))
        row.stock_set_at = item.get("stock_set_at")
    elif kind == "dose_logs":
        row.scheduled_at = _dt(item["scheduled_at"])
        row.status, row.note = item["status"], item.get("note") or ""
        row.acted_at, row.snoozed_until = _dt(item.get("acted_at")), _dt(item.get("snoozed_until"))
        row.taken_utc = item.get("taken_utc")
    elif kind == "water_logs":
        row.amount_ml, row.kind, row.logged_at = int(item["amount_ml"]), item.get("kind", "copo"), _dt(item["logged_at"])
    elif kind == "contacts":
        row.name, row.relation = item["name"][:120], (item.get("relation") or "")[:80]
        row.phone, row.is_doctor = (item.get("phone") or "")[:40], bool(item.get("is_doctor"))


def to_wire(kind: str, row, med_uuid: dict[int, str]) -> dict:
    base = {"uuid": row.uuid, "updated_at": row.updated_at, "deleted": row.deleted}
    if kind == "medications":
        base.update(name=row.name, strength=row.strength, form=row.form, dose_units=row.dose_units,
                    frequency=row.frequency, times=[t for t in row.times.split(",") if t],
                    weekdays=[int(x) for x in row.weekdays.split(",") if x != ""], instructions=row.instructions,
                    start_date=row.start_date.isoformat() if row.start_date else None,
                    end_date=row.end_date.isoformat() if row.end_date else None, track_stock=row.track_stock,
                    stock_units=row.stock_units, stock_total=row.stock_total,
                    refill_alert_days=row.refill_alert_days, reminders=row.reminders, paused=row.paused,
                    stock_set_at=row.stock_set_at)
    elif kind == "dose_logs":
        iso = lambda v: v.isoformat(timespec="seconds") if v else None  # noqa: E731
        base.update(medication_uuid=med_uuid.get(row.medication_id), scheduled_at=iso(row.scheduled_at),
                    status=row.status, acted_at=iso(row.acted_at), snoozed_until=iso(row.snoozed_until), note=row.note,
                    taken_utc=row.taken_utc)
    elif kind == "water_logs":
        base.update(amount_ml=row.amount_ml, kind=row.kind, logged_at=row.logged_at.isoformat(timespec="seconds"))
    elif kind == "contacts":
        base.update(name=row.name, relation=row.relation, phone=row.phone, is_doctor=row.is_doctor)
    return base


class SyncService:
    def __init__(self, db: Session, patient: orm.Patient, can_write: bool) -> None:
        self.db = db
        self.patient = patient
        self.can_write = can_write

    def _med_uuid_map(self) -> dict[int, str]:
        rows = self.db.execute(select(orm.Medication.id, orm.Medication.uuid)
                               .where(orm.Medication.patient_id == self.patient.id)).all()
        return {i: u for i, u in rows}

    def apply(self, changes: dict) -> tuple[list[dict], int]:
        rejected: list[dict] = []
        applied = 0
        for kind in KINDS:
            items = changes.get(kind) or []
            for item in items:
                reason = self._apply_one(kind, item)
                if reason:
                    rejected.append({"kind": kind, "uuid": item.get("uuid"), "reason": reason})
                else:
                    applied += 1
        prof = changes.get("profile")
        if prof:
            if not self.can_write:
                rejected.append({"kind": "profile", "uuid": None, "reason": "somente leitura"})
            elif prof.get("updated_at", "") > (self.patient.profile_updated_at or ""):
                self.patient.profile = prof.get("data") or {}
                self.patient.profile_updated_at = prof["updated_at"]
                bump(self.db, self.patient)
                applied += 1
        return rejected, applied

    def _apply_one(self, kind: str, item: dict) -> str | None:
        if not self.can_write:
            return "somente leitura"
        problem = _validate(kind, item)
        if problem:
            return problem
        model = MODELS[kind]
        row = self.db.scalar(select(model).where(model.uuid == item["uuid"]))
        if row is not None and row.patient_id != self.patient.id:
            return "uuid pertence a outro paciente"

        med_id = None
        if kind == "dose_logs":
            med = self.db.scalar(select(orm.Medication).where(orm.Medication.uuid == item.get("medication_uuid"),
                                                              orm.Medication.patient_id == self.patient.id))
            if med is None:
                return "medicação desconhecida"
            med_id = med.id
            if row is None:  # mesma dose registrada em outro aparelho com outro uuid
                row = self.db.scalar(select(orm.DoseLog).where(
                    orm.DoseLog.medication_id == med_id, orm.DoseLog.scheduled_at == _dt(item["scheduled_at"])))

        if row is not None and row.updated_at >= item["updated_at"]:
            return None  # o servidor já tem uma versão igual ou mais nova: ignora (não é erro)
        if row is None:
            row = model(patient_id=self.patient.id, uuid=item["uuid"])
            if med_id:
                row.medication_id = med_id
            self.db.add(row)
        _assign(kind, row, item)
        row.deleted = bool(item.get("deleted"))
        row.updated_at = item["updated_at"]
        row.seq = bump(self.db, self.patient)
        self.db.flush()
        return None

    def changes_since(self, cursor: int) -> dict:
        med_uuid = self._med_uuid_map()
        out: dict = {}
        for kind, model in MODELS.items():
            rows = self.db.scalars(select(model).where(model.patient_id == self.patient.id, model.seq > cursor)
                                   .order_by(model.seq)).all()
            out[kind] = [to_wire(kind, r, med_uuid) for r in rows]
        if self.patient.profile_updated_at:
            out["profile"] = {"updated_at": self.patient.profile_updated_at, "data": self.patient.profile or {}}
        return out

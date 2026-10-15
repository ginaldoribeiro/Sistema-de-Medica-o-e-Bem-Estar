"""Repositórios: única camada que conhece SQL."""
from __future__ import annotations

import json
from datetime import date, datetime, time

from .db import Database
from .models import (
    AuditEntry,
    Contact,
    DoseLog,
    DoseStatus,
    Frequency,
    Medication,
    MedForm,
    Profile,
    WaterLog,
)


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value.isoformat()


class MedicationRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _from_row(r) -> Medication:
        return Medication(
            id=r["id"],
            name=r["name"],
            strength=r["strength"],
            form=MedForm(r["form"]),
            dose_units=r["dose_units"],
            frequency=Frequency(r["frequency"]),
            times=[time.fromisoformat(t) for t in r["times"].split(",") if t],
            weekdays=[int(x) for x in r["weekdays"].split(",") if x != ""],
            instructions=r["instructions"],
            start_date=_d(r["start_date"]),
            end_date=_d(r["end_date"]),
            track_stock=bool(r["track_stock"]),
            stock_units=r["stock_units"],
            stock_total=r["stock_total"],
            refill_alert_days=r["refill_alert_days"],
            reminders=bool(r["reminders"]),
            paused=bool(r["paused"]),
        )

    @staticmethod
    def _params(m: Medication) -> tuple:
        return (
            m.name.strip(),
            m.strength.strip(),
            m.form.value,
            m.dose_units,
            m.frequency.value,
            ",".join(sorted(t.strftime("%H:%M") for t in m.times)),
            ",".join(str(w) for w in sorted(set(m.weekdays))),
            m.instructions.strip(),
            _iso(m.start_date),
            _iso(m.end_date),
            int(m.track_stock),
            m.stock_units,
            m.stock_total,
            m.refill_alert_days,
            int(m.reminders),
            int(m.paused),
        )

    def list(self, include_paused: bool = True) -> list[Medication]:
        sql = "SELECT * FROM medications"
        if not include_paused:
            sql += " WHERE paused = 0"
        sql += " ORDER BY paused, name COLLATE NOCASE"
        return [self._from_row(r) for r in self.db.query(sql)]

    def get(self, med_id: int) -> Medication | None:
        r = self.db.query_one("SELECT * FROM medications WHERE id = ?", (med_id,))
        return self._from_row(r) if r else None

    def add(self, m: Medication) -> Medication:
        m.id = self.db.execute(
            """INSERT INTO medications (name, strength, form, dose_units, frequency, times, weekdays,
               instructions, start_date, end_date, track_stock, stock_units, stock_total,
               refill_alert_days, reminders, paused) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            self._params(m),
        )
        return m

    def update(self, m: Medication) -> Medication:
        if m.id is None:
            raise ValueError("Medicação sem id não pode ser atualizada")
        self.db.execute(
            """UPDATE medications SET name=?, strength=?, form=?, dose_units=?, frequency=?, times=?,
               weekdays=?, instructions=?, start_date=?, end_date=?, track_stock=?, stock_units=?,
               stock_total=?, refill_alert_days=?, reminders=?, paused=? WHERE id=?""",
            self._params(m) + (m.id,),
        )
        return m

    def adjust_stock(self, med_id: int, delta: float) -> None:
        self.db.execute(
            "UPDATE medications SET stock_units = MAX(0, stock_units + ?) WHERE id = ? AND track_stock = 1",
            (delta, med_id),
        )

    def delete(self, med_id: int) -> None:
        self.db.execute("DELETE FROM medications WHERE id = ?", (med_id,))


class DoseLogRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _from_row(r) -> DoseLog:
        return DoseLog(
            id=r["id"],
            medication_id=r["medication_id"],
            scheduled_at=datetime.fromisoformat(r["scheduled_at"]),
            status=DoseStatus(r["status"]),
            acted_at=_dt(r["acted_at"]),
            snoozed_until=_dt(r["snoozed_until"]),
            note=r["note"],
        )

    def between(self, start: datetime, end: datetime) -> list[DoseLog]:
        rows = self.db.query(
            "SELECT * FROM dose_logs WHERE scheduled_at >= ? AND scheduled_at < ? ORDER BY scheduled_at",
            (_iso(start), _iso(end)),
        )
        return [self._from_row(r) for r in rows]

    def get(self, med_id: int, scheduled_at: datetime) -> DoseLog | None:
        r = self.db.query_one(
            "SELECT * FROM dose_logs WHERE medication_id = ? AND scheduled_at = ?",
            (med_id, _iso(scheduled_at)),
        )
        return self._from_row(r) if r else None

    def upsert(self, log: DoseLog) -> None:
        self.db.execute(
            """INSERT INTO dose_logs (medication_id, scheduled_at, status, acted_at, snoozed_until, note)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(medication_id, scheduled_at) DO UPDATE SET
                 status=excluded.status, acted_at=excluded.acted_at,
                 snoozed_until=excluded.snoozed_until, note=excluded.note""",
            (
                log.medication_id,
                _iso(log.scheduled_at),
                log.status.value,
                _iso(log.acted_at),
                _iso(log.snoozed_until),
                log.note,
            ),
        )

    def delete(self, med_id: int, scheduled_at: datetime) -> None:
        self.db.execute(
            "DELETE FROM dose_logs WHERE medication_id = ? AND scheduled_at = ?",
            (med_id, _iso(scheduled_at)),
        )

    def all(self) -> list[DoseLog]:
        return [self._from_row(r) for r in self.db.query("SELECT * FROM dose_logs ORDER BY scheduled_at")]


class WaterRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, log: WaterLog) -> WaterLog:
        log.id = self.db.execute(
            "INSERT INTO water_logs (amount_ml, kind, logged_at) VALUES (?,?,?)",
            (log.amount_ml, log.kind, _iso(log.logged_at)),
        )
        return log

    def between(self, start: datetime, end: datetime) -> list[WaterLog]:
        rows = self.db.query(
            "SELECT * FROM water_logs WHERE logged_at >= ? AND logged_at < ? ORDER BY logged_at DESC",
            (_iso(start), _iso(end)),
        )
        return [WaterLog(id=r["id"], amount_ml=r["amount_ml"], kind=r["kind"],
                         logged_at=datetime.fromisoformat(r["logged_at"])) for r in rows]

    def delete(self, log_id: int) -> None:
        self.db.execute("DELETE FROM water_logs WHERE id = ?", (log_id,))


class ContactRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[Contact]:
        rows = self.db.query("SELECT * FROM contacts ORDER BY is_doctor, name COLLATE NOCASE")
        return [Contact(id=r["id"], name=r["name"], relation=r["relation"], phone=r["phone"],
                        is_doctor=bool(r["is_doctor"])) for r in rows]

    def add(self, c: Contact) -> Contact:
        c.id = self.db.execute(
            "INSERT INTO contacts (name, relation, phone, is_doctor) VALUES (?,?,?,?)",
            (c.name.strip(), c.relation.strip(), c.phone.strip(), int(c.is_doctor)),
        )
        return c

    def delete(self, contact_id: int) -> None:
        self.db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))


class SettingsRepository:
    """Chave/valor em JSON — perfil, preferências, estado de segurança."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default=None):
        r = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(r["value"]) if r else default

    def set(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    def delete(self, key: str) -> None:
        self.db.execute("DELETE FROM settings WHERE key = ?", (key,))

    def all(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.db.query("SELECT key, value FROM settings")}

    # Perfil -----------------------------------------------------------------
    def profile(self) -> Profile:
        data = self.get("profile", {}) or {}
        if data.get("birth_date"):
            data["birth_date"] = date.fromisoformat(data["birth_date"])
        known = {k: v for k, v in data.items() if k in Profile.__dataclass_fields__}
        return Profile(**known)

    def save_profile(self, p: Profile) -> None:
        data = dict(p.__dict__)
        data["birth_date"] = _iso(p.birth_date)
        self.set("profile", data)


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, event: str, detail: str, at: datetime) -> None:
        self.db.execute(
            "INSERT INTO audit_log (event, detail, created_at) VALUES (?,?,?)",
            (event, detail, _iso(at)),
        )

    def recent(self, limit: int = 50) -> list[AuditEntry]:
        rows = self.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [AuditEntry(id=r["id"], event=r["event"], detail=r["detail"],
                           created_at=datetime.fromisoformat(r["created_at"])) for r in rows]

"""Repositórios: única camada que conhece SQL.

Toda escrita em tabelas sincronizáveis grava ``uuid`` (identidade global),
``updated_at`` (UTC, para "última escrita vence") e ``dirty = 1`` (precisa
subir para o servidor). Exclusões são lógicas (``deleted = 1``) para que a
remoção também chegue aos outros aparelhos.
"""
from __future__ import annotations

import json
import uuid as uuidlib
from datetime import date, datetime, time, timezone

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


def utcnow_iso() -> str:
    """Carimbo de alteração em UTC com microssegundos (comparável como texto)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")


def new_uuid() -> str:
    return uuidlib.uuid4().hex


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
            stock_units=r["stock_effective"] if "stock_effective" in r.keys() else r["stock_units"],
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

    # Estoque efetivo = base informada pelo usuário - doses tomadas depois dela.
    # Assim dois aparelhos que registram doses offline convergem: cada registro de dose
    # chega por sincronização e desconta uma única vez, em qualquer aparelho.
    # (COUNT dentro da subconsulta: um SUM(m.dose_units) viraria agregação da consulta externa.)
    SELECT = """SELECT m.*, MAX(0, m.stock_units - m.dose_units * (
                   SELECT COUNT(*) FROM dose_logs d
                   WHERE d.medication_id = m.id AND d.deleted = 0 AND d.status = 'taken'
                     AND d.taken_utc IS NOT NULL AND (m.stock_set_at IS NULL OR d.taken_utc > m.stock_set_at)
                 )) AS stock_effective
                FROM medications m"""

    def list(self, include_paused: bool = True) -> list[Medication]:
        sql = self.SELECT + " WHERE deleted = 0"
        if not include_paused:
            sql += " AND paused = 0"
        sql += " ORDER BY paused, name COLLATE NOCASE"
        return [self._from_row(r) for r in self.db.query(sql)]

    def get(self, med_id: int) -> Medication | None:
        r = self.db.query_one(self.SELECT + " WHERE id = ? AND deleted = 0", (med_id,))
        return self._from_row(r) if r else None

    def uuid_of(self, med_id: int) -> str | None:
        r = self.db.query_one("SELECT uuid FROM medications WHERE id = ?", (med_id,))
        return r["uuid"] if r else None

    def add(self, m: Medication) -> Medication:
        m.id = self.db.execute(
            """INSERT INTO medications (name, strength, form, dose_units, frequency, times, weekdays,
               instructions, start_date, end_date, track_stock, stock_units, stock_total,
               refill_alert_days, reminders, paused, uuid, updated_at, stock_set_at, dirty)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            self._params(m) + (new_uuid(), now := utcnow_iso(), now),
        )
        return m

    def update(self, m: Medication) -> Medication:
        if m.id is None:
            raise ValueError("Medicação sem id não pode ser atualizada")
        current = self.get(m.id)
        now = utcnow_iso()
        if current is not None and abs(current.stock_units - m.stock_units) < 1e-9:
            # Estoque não mudou: mantém a base e o momento dela (não "engole" doses de outros aparelhos).
            params = self._params(m)
            self.db.execute(
                """UPDATE medications SET name=?, strength=?, form=?, dose_units=?, frequency=?, times=?,
                   weekdays=?, instructions=?, start_date=?, end_date=?, track_stock=?,
                   stock_total=?, refill_alert_days=?, reminders=?, paused=?, updated_at=?, dirty=1 WHERE id=?""",
                params[:11] + params[12:] + (now, m.id),
            )
        else:
            # Usuário informou um novo estoque (reposição/correção): vira a nova base.
            self.db.execute(
                """UPDATE medications SET name=?, strength=?, form=?, dose_units=?, frequency=?, times=?,
                   weekdays=?, instructions=?, start_date=?, end_date=?, track_stock=?, stock_units=?,
                   stock_total=?, refill_alert_days=?, reminders=?, paused=?, updated_at=?, stock_set_at=?,
                   dirty=1 WHERE id=?""",
                self._params(m) + (now, now, m.id),
            )
        return m

    def adjust_stock(self, med_id: int, delta: float) -> None:
        """Sem efeito: o estoque é derivado dos registros de dose (ver SELECT)."""

    def delete(self, med_id: int) -> None:
        now = utcnow_iso()
        with self.db.transaction() as conn:
            conn.execute("UPDATE medications SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?", (now, med_id))
            conn.execute("UPDATE dose_logs SET deleted = 1, updated_at = ?, dirty = 1 WHERE medication_id = ?",
                         (now, med_id))


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
            """SELECT * FROM dose_logs WHERE deleted = 0 AND scheduled_at >= ? AND scheduled_at < ?
               ORDER BY scheduled_at""",
            (_iso(start), _iso(end)),
        )
        return [self._from_row(r) for r in rows]

    def get(self, med_id: int, scheduled_at: datetime) -> DoseLog | None:
        r = self.db.query_one(
            "SELECT * FROM dose_logs WHERE medication_id = ? AND scheduled_at = ? AND deleted = 0",
            (med_id, _iso(scheduled_at)),
        )
        return self._from_row(r) if r else None

    def upsert(self, log: DoseLog) -> None:
        now = utcnow_iso()
        taken = now if log.status == DoseStatus.TAKEN else None
        self.db.execute(
            """INSERT INTO dose_logs (medication_id, scheduled_at, status, acted_at, snoozed_until, note,
                                      uuid, updated_at, taken_utc, deleted, dirty)
               VALUES (?,?,?,?,?,?,?,?,?,0,1)
               ON CONFLICT(medication_id, scheduled_at) DO UPDATE SET
                 taken_utc = CASE WHEN excluded.status = 'taken'
                                  THEN COALESCE(CASE WHEN dose_logs.status = 'taken' AND dose_logs.deleted = 0
                                                     THEN dose_logs.taken_utc END, excluded.taken_utc)
                                  ELSE NULL END,
                 status=excluded.status, acted_at=excluded.acted_at, snoozed_until=excluded.snoozed_until,
                 note=excluded.note, updated_at=excluded.updated_at, deleted=0, dirty=1""",
            (
                log.medication_id,
                _iso(log.scheduled_at),
                log.status.value,
                _iso(log.acted_at),
                _iso(log.snoozed_until),
                log.note,
                new_uuid(),
                now,
                taken,
            ),
        )

    def delete(self, med_id: int, scheduled_at: datetime) -> None:
        self.db.execute(
            "UPDATE dose_logs SET deleted = 1, updated_at = ?, dirty = 1 WHERE medication_id = ? AND scheduled_at = ?",
            (utcnow_iso(), med_id, _iso(scheduled_at)),
        )

    def all(self) -> list[DoseLog]:
        return [self._from_row(r) for r in
                self.db.query("SELECT * FROM dose_logs WHERE deleted = 0 ORDER BY scheduled_at")]


class WaterRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, log: WaterLog) -> WaterLog:
        log.id = self.db.execute(
            "INSERT INTO water_logs (amount_ml, kind, logged_at, uuid, updated_at, dirty) VALUES (?,?,?,?,?,1)",
            (log.amount_ml, log.kind, _iso(log.logged_at), new_uuid(), utcnow_iso()),
        )
        return log

    def between(self, start: datetime, end: datetime) -> list[WaterLog]:
        rows = self.db.query(
            """SELECT * FROM water_logs WHERE deleted = 0 AND logged_at >= ? AND logged_at < ?
               ORDER BY logged_at DESC""",
            (_iso(start), _iso(end)),
        )
        return [WaterLog(id=r["id"], amount_ml=r["amount_ml"], kind=r["kind"],
                         logged_at=datetime.fromisoformat(r["logged_at"])) for r in rows]

    def delete(self, log_id: int) -> None:
        self.db.execute("UPDATE water_logs SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?",
                        (utcnow_iso(), log_id))


class ContactRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[Contact]:
        rows = self.db.query("SELECT * FROM contacts WHERE deleted = 0 ORDER BY is_doctor, name COLLATE NOCASE")
        return [Contact(id=r["id"], name=r["name"], relation=r["relation"], phone=r["phone"],
                        is_doctor=bool(r["is_doctor"])) for r in rows]

    def add(self, c: Contact) -> Contact:
        c.id = self.db.execute(
            "INSERT INTO contacts (name, relation, phone, is_doctor, uuid, updated_at, dirty) VALUES (?,?,?,?,?,?,1)",
            (c.name.strip(), c.relation.strip(), c.phone.strip(), int(c.is_doctor), new_uuid(), utcnow_iso()),
        )
        return c

    def delete(self, contact_id: int) -> None:
        self.db.execute("UPDATE contacts SET deleted = 1, updated_at = ?, dirty = 1 WHERE id = ?",
                        (utcnow_iso(), contact_id))


class SettingsRepository:
    """Chave/valor em JSON — perfil, preferências, estado de segurança e de sincronização."""

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

    # Perfil (também sincronizado) ---------------------------------------------
    def profile(self) -> Profile:
        data = self.get("profile", {}) or {}
        if data.get("birth_date"):
            data["birth_date"] = date.fromisoformat(data["birth_date"])
        known = {k: v for k, v in data.items() if k in Profile.__dataclass_fields__}
        return Profile(**known)

    @staticmethod
    def profile_to_dict(p: Profile) -> dict:
        data = dict(p.__dict__)
        data["birth_date"] = _iso(p.birth_date)
        return data

    def save_profile(self, p: Profile, from_remote_at: str | None = None) -> None:
        self.set("profile", self.profile_to_dict(p))
        self.set("profile_meta", {"updated_at": from_remote_at or utcnow_iso(), "dirty": from_remote_at is None})


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

"""Sincronização offline-first entre o cache local (SQLite) e o servidor.

Protocolo (uma ida e volta):

    POST /api/v1/patients/{id}/sync
    {"cursor": 41, "changes": {"medications": [...], "dose_logs": [...], ...}}
    -> {"cursor": 57, "changes": {...alterações do servidor desde o cursor 41...},
        "rejected": [{"kind": "...", "uuid": "...", "reason": "..."}]}

* Cada registro tem ``uuid`` global e ``updated_at`` (UTC). Conflito = a
  escrita mais recente vence (last-write-wins).
* O servidor numera cada alteração com um ``seq`` crescente por paciente; o
  cliente guarda o último ``cursor`` e pede só o que mudou depois dele.
* Registros de dose referenciam a medicação pelo ``medication_uuid`` porque os
  ids inteiros são diferentes em cada aparelho.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .db import Database
from .repositories import SettingsRepository

KINDS = ("medications", "dose_logs", "water_logs", "contacts")

FIELDS = {
    "medications": ["name", "strength", "form", "dose_units", "frequency", "times", "weekdays", "instructions",
                    "start_date", "end_date", "track_stock", "stock_units", "stock_total", "refill_alert_days",
                    "reminders", "paused", "stock_set_at"],
    "dose_logs": ["scheduled_at", "status", "acted_at", "snoozed_until", "note", "taken_utc"],
    "water_logs": ["amount_ml", "kind", "logged_at"],
    "contacts": ["name", "relation", "phone", "is_doctor"],
}
BOOL_FIELDS = {"track_stock", "reminders", "paused", "is_doctor"}


# --------------------------------------------------------------- formato de fio
def row_to_wire(kind: str, row, med_uuid: str | None = None) -> dict:
    """Linha do SQLite local -> dicionário do protocolo."""
    item = {"uuid": row["uuid"], "updated_at": row["updated_at"], "deleted": bool(row["deleted"])}
    for f in FIELDS[kind]:
        v = row[f]
        if f in BOOL_FIELDS:
            v = bool(v)
        elif f == "times":
            v = [t for t in v.split(",") if t]
        elif f == "weekdays":
            v = [int(x) for x in v.split(",") if x != ""]
        item[f] = v
    if kind == "dose_logs":
        item["medication_uuid"] = med_uuid
    return item


def wire_to_columns(kind: str, item: dict) -> dict:
    """Dicionário do protocolo -> colunas do SQLite local (sem medication_id)."""
    cols = {}
    for f in FIELDS[kind]:
        v = item.get(f)
        if f in BOOL_FIELDS:
            v = int(bool(v))
        elif f == "times":
            v = ",".join(sorted(v or []))
        elif f == "weekdays":
            v = ",".join(str(x) for x in sorted(set(v or [])))
        elif f in ("instructions", "strength", "note", "relation", "phone") and v is None:
            v = ""
        cols[f] = v
    return cols


# ------------------------------------------------------------- lado do cliente
class LocalSyncStore:
    """Lê alterações pendentes e aplica alterações remotas no SQLite local."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.settings = SettingsRepository(db)

    # Pendências -------------------------------------------------------------
    def pending_count(self) -> int:
        total = sum(self.db.query_one(f"SELECT COUNT(*) AS n FROM {k} WHERE dirty = 1")["n"] for k in KINDS)
        meta = self.settings.get("profile_meta") or {}
        return total + (1 if meta.get("dirty") else 0)

    def collect(self) -> dict:
        changes: dict[str, list] = {}
        for kind in KINDS:
            if kind == "dose_logs":
                rows = self.db.query("""SELECT d.*, m.uuid AS med_uuid FROM dose_logs d
                                        JOIN medications m ON m.id = d.medication_id WHERE d.dirty = 1""")
                changes[kind] = [row_to_wire(kind, r, r["med_uuid"]) for r in rows]
            else:
                changes[kind] = [row_to_wire(kind, r) for r in self.db.query(f"SELECT * FROM {kind} WHERE dirty = 1")]
        meta = self.settings.get("profile_meta") or {}
        if meta.get("dirty"):
            changes["profile"] = {"updated_at": meta["updated_at"], "data": self.settings.get("profile", {})}
        return changes

    def mark_clean(self, sent: dict) -> None:
        """Limpa o "sujo" só do que não mudou de novo enquanto a sincronização acontecia."""
        with self.db.transaction() as conn:
            for kind in KINDS:
                for item in sent.get(kind, []):
                    conn.execute(f"UPDATE {kind} SET dirty = 0 WHERE uuid = ? AND updated_at = ?",
                                 (item["uuid"], item["updated_at"]))
        if "profile" in sent:
            meta = self.settings.get("profile_meta") or {}
            if meta.get("updated_at") == sent["profile"]["updated_at"]:
                self.settings.set("profile_meta", {**meta, "dirty": False})

    # Aplicação de alterações remotas -------------------------------------------
    def apply(self, changes: dict) -> int:
        applied = 0
        with self.db.transaction() as conn:
            for kind in KINDS:  # medications primeiro: os logs dependem delas
                for item in changes.get(kind, []):
                    applied += self._apply_one(conn, kind, item)
        prof = changes.get("profile")
        if prof:
            meta = self.settings.get("profile_meta") or {}
            same = meta.get("updated_at") == prof["updated_at"] and not meta.get("dirty")
            if not same and not (meta.get("dirty") and meta.get("updated_at", "") > prof["updated_at"]):
                self.settings.set("profile", prof["data"])
                self.settings.set("profile_meta", {"updated_at": prof["updated_at"], "dirty": False})
                applied += 1
        return applied

    def _apply_one(self, conn, kind: str, item: dict) -> int:
        cols = wire_to_columns(kind, item)
        if kind == "dose_logs":
            med = conn.execute("SELECT id FROM medications WHERE uuid = ?", (item.get("medication_uuid"),)).fetchone()
            if med is None:
                return 0
            cols["medication_id"] = med["id"]
        cols.update(uuid=item["uuid"], updated_at=item["updated_at"], deleted=int(bool(item.get("deleted"))), dirty=0)

        existing = conn.execute(f"SELECT id, updated_at, dirty FROM {kind} WHERE uuid = ?", (item["uuid"],)).fetchone()
        if existing is None and kind == "dose_logs":
            # Mesma dose registrada offline em dois aparelhos: unifica pela chave natural.
            existing = conn.execute(
                "SELECT id, updated_at, dirty FROM dose_logs WHERE medication_id = ? AND scheduled_at = ?",
                (cols["medication_id"], cols["scheduled_at"])).fetchone()
        if existing is not None:
            if existing["updated_at"] == item["updated_at"] and not existing["dirty"]:
                return 0  # eco do que este aparelho acabou de enviar
            if existing["dirty"] and existing["updated_at"] > item["updated_at"]:
                return 0  # a versão local é mais nova e ainda vai subir
            sets = ", ".join(f"{k} = ?" for k in cols)
            conn.execute(f"UPDATE {kind} SET {sets} WHERE id = ?", tuple(cols.values()) + (existing["id"],))
        else:
            names = ", ".join(cols)
            conn.execute(f"INSERT INTO {kind} ({names}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
        return 1


class SyncTransport(Protocol):
    def sync(self, patient_id: str, cursor: int, changes: dict) -> dict: ...


@dataclass
class SyncResult:
    ok: bool
    pushed: int = 0
    pulled: int = 0
    rejected: list = field(default_factory=list)
    error: str = ""
    at: datetime | None = None


class SyncEngine:
    def __init__(self, db: Database, transport: SyncTransport, patient_id: str) -> None:
        self.store = LocalSyncStore(db)
        self.transport = transport
        self.patient_id = patient_id
        self.last: SyncResult | None = None

    @property
    def cursor(self) -> int:
        return int(self.store.settings.get("sync_cursor", 0) or 0)

    def sync(self) -> SyncResult:
        changes = self.store.collect()
        pushed = sum(len(changes.get(k, [])) for k in KINDS) + (1 if "profile" in changes else 0)
        try:
            resp = self.transport.sync(self.patient_id, self.cursor, changes)
        except Exception as exc:  # sem rede, servidor fora do ar, sessão expirada...
            self.last = SyncResult(False, error=_friendly(exc), at=datetime.now())
            return self.last
        self.store.mark_clean(changes)
        pulled = self.store.apply(resp.get("changes", {}))
        self.store.settings.set("sync_cursor", resp.get("cursor", self.cursor))
        if resp.get("rejected"):
            # Algo foi recusado (ex.: acesso somente leitura): baixa tudo de novo para
            # desfazer no aparelho o que o servidor não aceitou.
            try:
                full = self.transport.sync(self.patient_id, 0, {})
                pulled += self.store.apply(full.get("changes", {}))
                self.store.settings.set("sync_cursor", full.get("cursor", self.cursor))
            except Exception:
                self.store.settings.set("sync_cursor", 0)
        self.store.settings.set("last_sync_at", datetime.now().isoformat(timespec="seconds"))
        self.last = SyncResult(True, pushed, pulled, resp.get("rejected", []), at=datetime.now())
        return self.last


def _friendly(exc: Exception) -> str:
    name = type(exc).__name__
    if "Connect" in name or "Timeout" in name or "Network" in name:
        return "Sem conexão com o servidor. As alterações ficam guardadas e sobem depois."
    return str(exc) or name

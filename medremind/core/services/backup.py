"""Backup e restauração em JSON com verificação de integridade (SHA-256)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..db import Database
from .audit import AuditService

FORMAT = "medremind-backup"
TABLES = ["medications", "dose_logs", "water_logs", "contacts", "settings"]
# Credenciais nunca saem do aparelho.
EXCLUDED_SETTINGS = {"pin", "pin_attempts"}


class BackupError(ValueError):
    pass


def _checksum(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class BackupService:
    def __init__(self, db: Database, audit: AuditService, clock: Callable[[], datetime] = datetime.now) -> None:
        self.db = db
        self.audit = audit
        self.clock = clock

    def export_dict(self) -> dict:
        data: dict[str, list[dict]] = {}
        for table in TABLES:
            rows = [dict(r) for r in self.db.query(f"SELECT * FROM {table}")]
            if table == "settings":
                rows = [r for r in rows if r["key"] not in EXCLUDED_SETTINGS]
            data[table] = rows
        return {
            "format": FORMAT,
            "schema_version": self.db.version,
            "exported_at": self.clock().isoformat(timespec="seconds"),
            "data": data,
            "sha256": _checksum(data),
        }

    def export_file(self, folder: str | Path) -> Path:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"medremind-backup-{self.clock():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(self.export_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.audit.log("backup_exportado", path.name)
        return path

    def import_dict(self, payload: dict) -> dict[str, int]:
        if payload.get("format") != FORMAT:
            raise BackupError("Arquivo não é um backup do MedRemind.")
        if payload.get("schema_version", 0) > self.db.version:
            raise BackupError("Backup feito por uma versão mais nova do app. Atualize o app.")
        data = payload.get("data")
        if not isinstance(data, dict) or _checksum(data) != payload.get("sha256"):
            raise BackupError("Backup corrompido ou alterado (verificação de integridade falhou).")

        counts: dict[str, int] = {}
        with self.db.transaction() as conn:
            for table in reversed(TABLES):
                if table == "settings":
                    conn.execute("DELETE FROM settings WHERE key NOT IN ({})".format(
                        ",".join("?" * len(EXCLUDED_SETTINGS))), tuple(EXCLUDED_SETTINGS))
                else:
                    conn.execute(f"DELETE FROM {table}")
            for table in TABLES:
                rows = data.get(table, [])
                for row in rows:
                    if table == "settings" and row.get("key") in EXCLUDED_SETTINGS:
                        continue
                    cols = list(row.keys())
                    if not all(c.replace("_", "").isalnum() for c in cols):
                        raise BackupError("Coluna inválida no backup.")
                    conn.execute(
                        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        tuple(row[c] for c in cols),
                    )
                counts[table] = len(rows)
        self.audit.log("backup_importado", f"{counts.get('medications', 0)} medicações")
        return counts

    def import_file(self, path: str | Path) -> dict[str, int]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError(f"Não foi possível ler o arquivo: {exc}") from exc
        return self.import_dict(payload)

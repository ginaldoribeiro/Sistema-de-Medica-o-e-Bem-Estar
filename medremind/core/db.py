"""Acesso ao SQLite com migrações versionadas.

Os dados de saúde ficam no próprio aparelho (offline-first). O schema evolui
por migrações numeradas, registradas em ``PRAGMA user_version``.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS: list[str] = [
    # 1 — schema inicial
    """
    CREATE TABLE medications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        strength TEXT NOT NULL DEFAULT '',
        form TEXT NOT NULL,
        dose_units REAL NOT NULL DEFAULT 1,
        frequency TEXT NOT NULL,
        times TEXT NOT NULL DEFAULT '',
        weekdays TEXT NOT NULL DEFAULT '',
        instructions TEXT NOT NULL DEFAULT '',
        start_date TEXT,
        end_date TEXT,
        track_stock INTEGER NOT NULL DEFAULT 1,
        stock_units REAL NOT NULL DEFAULT 0,
        stock_total REAL NOT NULL DEFAULT 0,
        refill_alert_days INTEGER NOT NULL DEFAULT 7,
        reminders INTEGER NOT NULL DEFAULT 1,
        paused INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE dose_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
        scheduled_at TEXT NOT NULL,
        status TEXT NOT NULL,
        acted_at TEXT,
        snoozed_until TEXT,
        note TEXT NOT NULL DEFAULT '',
        UNIQUE (medication_id, scheduled_at)
    );
    CREATE INDEX idx_dose_logs_sched ON dose_logs(scheduled_at);
    CREATE TABLE water_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount_ml INTEGER NOT NULL,
        kind TEXT NOT NULL DEFAULT 'copo',
        logged_at TEXT NOT NULL
    );
    CREATE INDEX idx_water_logged ON water_logs(logged_at);
    CREATE TABLE contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        relation TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        is_doctor INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    """,
]


class Database:
    """Conexão única e thread-safe (o Flet chama handlers em threads diferentes)."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self.migrate()

    @property
    def version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def migrate(self) -> None:
        with self._lock:
            current = self.version
            for number, script in enumerate(MIGRATIONS, start=1):
                if number <= current:
                    continue
                self._conn.execute("BEGIN")
                try:
                    for statement in filter(str.strip, script.split(";")):
                        self._conn.execute(statement)
                    self._conn.execute(f"PRAGMA user_version = {number}")
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Executa e devolve o lastrowid (útil em INSERT)."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.lastrowid

    def close(self) -> None:
        with self._lock:
            self._conn.close()

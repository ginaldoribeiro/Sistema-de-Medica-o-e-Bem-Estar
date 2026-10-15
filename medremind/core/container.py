"""Composição das dependências (injeção manual, sem framework)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .db import Database
from .repositories import (
    AuditRepository,
    ContactRepository,
    DoseLogRepository,
    MedicationRepository,
    SettingsRepository,
    WaterRepository,
)
from .services.assistant import Assistant, AssistantTools
from .services.audit import AuditService
from .services.backup import BackupService
from .services.hydration import HydrationService
from .services.medications import MedicationService
from .services.reminders import ReminderEngine
from .services.reports import ReportService
from .services.schedule import ScheduleService
from .services.security import SecurityService


def default_data_dir() -> Path:
    env = os.environ.get("MEDREMIND_DATA_DIR")
    if env:
        return Path(env)
    # FLET_APP_STORAGE_DATA é definido pelo Flet nos builds móveis/desktop.
    flet_dir = os.environ.get("FLET_APP_STORAGE_DATA")
    return Path(flet_dir) if flet_dir else Path.home() / ".medremind"


@dataclass
class Container:
    db: Database
    settings: SettingsRepository
    contacts: ContactRepository
    audit: AuditService
    meds: MedicationService
    schedule: ScheduleService
    hydration: HydrationService
    security: SecurityService
    reminders: ReminderEngine
    backup: BackupService
    reports: ReportService
    assistant: Assistant
    data_dir: Path

    @classmethod
    def build(cls, db_path: str | Path | None = None, clock: Callable[[], datetime] = datetime.now,
              api_key: str | None = None) -> "Container":
        data_dir = default_data_dir()
        if db_path is None:
            db_path = data_dir / "medremind.db"
        db = Database(db_path)
        settings = SettingsRepository(db)
        contacts = ContactRepository(db)
        audit = AuditService(AuditRepository(db), clock)
        med_repo = MedicationRepository(db)
        meds = MedicationService(med_repo, audit, clock)
        schedule = ScheduleService(med_repo, DoseLogRepository(db), audit, clock)
        hydration = HydrationService(WaterRepository(db), settings, clock)
        tools = AssistantTools(schedule, meds, hydration, contacts)
        return cls(
            db=db,
            settings=settings,
            contacts=contacts,
            audit=audit,
            meds=meds,
            schedule=schedule,
            hydration=hydration,
            security=SecurityService(settings, audit, clock),
            reminders=ReminderEngine(schedule, settings, clock),
            backup=BackupService(db, audit, clock),
            reports=ReportService(schedule, meds, settings, audit, clock),
            assistant=Assistant(tools, api_key),
            data_dir=Path(db_path).parent if str(db_path) != ":memory:" else data_dir,
        )

    # Estado do primeiro uso -------------------------------------------------
    @property
    def onboarded(self) -> bool:
        return bool(self.settings.get("onboarded", False))

    @property
    def consent_given(self) -> bool:
        return bool(self.settings.get("consent_at"))

    def give_consent(self, analytics: bool = False) -> None:
        self.settings.set("consent_at", datetime.now().isoformat(timespec="seconds"))
        self.settings.set("consent_analytics", analytics)
        self.audit.log("consentimento", "LGPD — dados de saúde armazenados no aparelho")

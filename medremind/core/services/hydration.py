"""Rastreio de hidratação."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from ..models import WaterLog
from ..repositories import SettingsRepository, WaterRepository

PRESETS = {"copo": 200, "garrafa": 500}


@dataclass
class WaterDay:
    total_ml: int
    goal_ml: int
    logs: list[WaterLog]

    @property
    def ratio(self) -> float:
        return min(1.0, self.total_ml / self.goal_ml) if self.goal_ml else 0.0


class HydrationService:
    def __init__(self, repo: WaterRepository, settings: SettingsRepository,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.repo = repo
        self.settings = settings
        self.clock = clock

    def add(self, amount_ml: int, kind: str = "copo") -> WaterLog:
        if not 0 < amount_ml <= 3000:
            raise ValueError("Quantidade inválida (1 a 3000 ml).")
        return self.repo.add(WaterLog(amount_ml=amount_ml, kind=kind, logged_at=self.clock()))

    def add_preset(self, kind: str) -> WaterLog:
        return self.add(PRESETS[kind], kind)

    def today(self) -> WaterDay:
        start = datetime.combine(self.clock().date(), datetime.min.time())
        logs = self.repo.between(start, start + timedelta(days=1))
        goal = self.settings.profile().water_goal_ml or 2000
        return WaterDay(sum(l.amount_ml for l in logs), goal, logs)

    def undo_last(self) -> bool:
        logs = self.today().logs
        if not logs:
            return False
        self.repo.delete(logs[0].id)
        return True

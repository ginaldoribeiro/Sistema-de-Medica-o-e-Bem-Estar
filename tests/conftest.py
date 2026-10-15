import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MEDREMIND_API_AUTOSTART", "0")
os.environ.pop("ANTHROPIC_API_KEY", None)

from medremind.core.container import Container  # noqa: E402


class FakeClock:
    """Relógio controlável para testar horários sem depender da hora real."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def set(self, *args) -> None:
        self.now = datetime(*args)


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 14, 12, 30))  # quarta-feira


@pytest.fixture
def c(clock, tmp_path, monkeypatch):
    monkeypatch.setenv("MEDREMIND_DATA_DIR", str(tmp_path))
    return Container.build(":memory:", clock=clock, api_key="")

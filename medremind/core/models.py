"""Modelos de domínio do MedRemind.

São dataclasses puras, sem dependência de banco ou de interface, para que o
núcleo possa ser usado pelo app (Flet), pela API (FastAPI) e pelos testes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum


class MedForm(str, Enum):
    COMPRIMIDO = "comprimido"
    CAPSULA = "capsula"
    LIQUIDO = "liquido"
    INJECAO = "injecao"
    GOTAS = "gotas"

    @property
    def label(self) -> str:
        return {
            "comprimido": "Comprimido",
            "capsula": "Cápsula",
            "liquido": "Líquido",
            "injecao": "Injeção",
            "gotas": "Gotas",
        }[self.value]


class Frequency(str, Enum):
    DAILY = "daily"          # todos os dias, nos horários definidos
    WEEKDAYS = "weekdays"    # apenas em dias específicos da semana
    AS_NEEDED = "as_needed"  # conforme necessário (sem lembrete fixo)

    @property
    def label(self) -> str:
        return {"daily": "Todos os dias", "weekdays": "Dias específicos", "as_needed": "Conforme necessário"}[self.value]


class DoseStatus(str, Enum):
    TAKEN = "taken"
    SKIPPED = "skipped"
    MISSED = "missed"      # calculado: passou da janela de tolerância sem registro
    DUE = "due"            # calculado: está no horário (dentro da janela)
    SNOOZED = "snoozed"    # adiado pelo usuário
    UPCOMING = "upcoming"  # calculado: ainda vai acontecer

    @property
    def label(self) -> str:
        return {
            "taken": "Tomado",
            "skipped": "Pulado",
            "missed": "Perdido",
            "due": "Agora",
            "snoozed": "Adiado",
            "upcoming": "Agendado",
        }[self.value]


UNITS = {
    MedForm.COMPRIMIDO: ("comprimido", "comprimidos"),
    MedForm.CAPSULA: ("cápsula", "cápsulas"),
    MedForm.LIQUIDO: ("ml", "ml"),
    MedForm.INJECAO: ("aplicação", "aplicações"),
    MedForm.GOTAS: ("gota", "gotas"),
}

WEEKDAY_LABELS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


@dataclass
class Medication:
    name: str
    strength: str = ""                     # ex.: "500mg"
    form: MedForm = MedForm.COMPRIMIDO
    dose_units: float = 1.0                # unidades consumidas por dose (ex.: 1 comprimido)
    frequency: Frequency = Frequency.DAILY
    times: list[time] = field(default_factory=list)
    weekdays: list[int] = field(default_factory=list)  # 0=segunda ... 6=domingo
    instructions: str = ""
    start_date: date | None = None
    end_date: date | None = None           # None = uso contínuo
    track_stock: bool = True
    stock_units: float = 0.0
    stock_total: float = 0.0               # tamanho da embalagem, para a barra de progresso
    refill_alert_days: int = 7
    reminders: bool = True
    paused: bool = False
    id: int | None = None

    @property
    def dose_text(self) -> str:
        """Quantidade por dose com a unidade certa: "1 comprimido", "20 gotas", "5 ml"."""
        singular, plural = UNITS[self.form]
        n = self.dose_units
        return f"{n:g} {singular if n == 1 else plural}"

    @property
    def display_name(self) -> str:
        return f"{self.name} {self.strength}".strip()

    def is_scheduled_on(self, day: date) -> bool:
        if self.paused or self.frequency == Frequency.AS_NEEDED:
            return False
        if self.start_date and day < self.start_date:
            return False
        if self.end_date and day > self.end_date:
            return False
        if self.frequency == Frequency.WEEKDAYS:
            return day.weekday() in self.weekdays
        return True

    @property
    def doses_per_day(self) -> float:
        """Média de doses por dia (considera dias da semana), usada na previsão de estoque."""
        if self.paused or self.frequency == Frequency.AS_NEEDED or not self.times:
            return 0.0
        per_day = len(self.times)
        if self.frequency == Frequency.WEEKDAYS:
            return per_day * len(self.weekdays) / 7
        return float(per_day)


@dataclass
class DoseLog:
    medication_id: int
    scheduled_at: datetime
    status: DoseStatus
    acted_at: datetime | None = None
    snoozed_until: datetime | None = None
    note: str = ""
    id: int | None = None


@dataclass
class PlannedDose:
    """Uma dose prevista para um dia, combinando a agenda com o que foi registrado."""
    medication: Medication
    scheduled_at: datetime
    status: DoseStatus
    acted_at: datetime | None = None
    snoozed_until: datetime | None = None

    @property
    def key(self) -> str:
        return f"{self.medication.id}@{self.scheduled_at.isoformat(timespec='minutes')}"


@dataclass
class WaterLog:
    amount_ml: int
    logged_at: datetime
    kind: str = "copo"
    id: int | None = None


@dataclass
class Contact:
    name: str
    relation: str = ""
    phone: str = ""
    is_doctor: bool = False
    id: int | None = None


@dataclass
class Profile:
    name: str = ""
    birth_date: date | None = None
    email: str = ""
    phone: str = ""
    health_id: str = ""
    blood_type: str = ""
    allergies: str = ""        # texto livre, mostrado no modo de emergência
    conditions: str = ""       # texto livre, mostrado no modo de emergência
    pharmacy_name: str = ""
    pharmacy_address: str = ""
    water_goal_ml: int = 2000


@dataclass
class AuditEntry:
    event: str
    detail: str
    created_at: datetime
    id: int | None = None

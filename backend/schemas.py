"""Contratos da API (Pydantic)."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from medremind.core.models import Frequency, MedForm


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=120)
    account_type: Literal["patient", "caregiver", "doctor"] = "patient"
    professional_id: str = Field("", max_length=40)
    timezone: str = "America/Sao_Paulo"
    accept_terms: bool

    @field_validator("accept_terms")
    @classmethod
    def must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("É preciso aceitar os termos de uso e privacidade")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    account_type: str
    patient_id: str | None


class PatientSummary(BaseModel):
    id: str
    name: str
    role: str
    can_write: bool


class MedicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    strength: str = Field("", max_length=40)
    form: MedForm = MedForm.COMPRIMIDO
    dose_units: float = Field(1, gt=0, le=1000)
    frequency: Frequency = Frequency.DAILY
    times: list[time] = []
    weekdays: list[int] = []
    instructions: str = Field("", max_length=500)
    start_date: date | None = None
    end_date: date | None = None
    track_stock: bool = True
    stock_units: float = Field(0, ge=0)
    stock_total: float = Field(0, ge=0)
    refill_alert_days: int = Field(7, ge=0, le=90)
    reminders: bool = True
    paused: bool = False


class DoseActionIn(BaseModel):
    medication_id: int
    scheduled_at: datetime
    action: Literal["take", "skip", "snooze", "undo"]
    minutes: int = Field(10, ge=1, le=240)


class WaterIn(BaseModel):
    amount_ml: int = Field(gt=0, le=3000)
    kind: str = Field("copo", max_length=20)


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    relation: str = Field("", max_length=80)
    phone: str = Field("", max_length=40)
    is_doctor: bool = False


class RefillIn(BaseModel):
    units: float = Field(gt=0, le=10000)


class InviteIn(BaseModel):
    role: Literal["caregiver", "doctor"]
    can_edit: bool = False


class AcceptInviteIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class MemberUpdateIn(BaseModel):
    can_edit: bool | None = None
    notify_missed: bool | None = None


class SyncIn(BaseModel):
    cursor: int = Field(0, ge=0)
    changes: dict = {}


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class DeviceIn(BaseModel):
    platform: Literal["android", "ios", "web", "desktop"]
    token: str = Field(min_length=10, max_length=400)


class DeleteAccountIn(BaseModel):
    password: str
    confirm: Literal["EXCLUIR"]

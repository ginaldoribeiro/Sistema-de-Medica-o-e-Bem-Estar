"""Modelo relacional do servidor."""
from __future__ import annotations

import uuid as uuidlib
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return uuidlib.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(32), unique=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(20), default="patient")  # patient | caregiver | doctor
    professional_id: Mapped[str] = mapped_column(String(40), default="")     # CRM/COREN, opcional
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    patient: Mapped["Patient | None"] = relationship(back_populates="owner", uselist=False,
                                                       cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family: Mapped[str] = mapped_column(String(32), index=True)  # rotação: reuso revoga a família toda
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(32), unique=True, default=new_uuid, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_updated_at: Mapped[str] = mapped_column(String(32), default="")
    sync_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[User] = relationship(back_populates="patient")


class CareLink(Base):
    """Acesso de um cuidador ou médico aos dados de um paciente."""
    __tablename__ = "care_links"
    __table_args__ = (UniqueConstraint("patient_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # caregiver | doctor
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_missed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship()
    patient: Mapped[Patient] = relationship()


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncMixin:
    """Colunas comuns às entidades sincronizadas."""
    uuid: Mapped[str] = mapped_column(String(32), unique=True, default=new_uuid, index=True)
    updated_at: Mapped[str] = mapped_column(String(32))  # ISO UTC com ms, vindo do cliente ou do servidor
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    seq: Mapped[int] = mapped_column(Integer, index=True)


class Medication(SyncMixin, Base):
    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    strength: Mapped[str] = mapped_column(String(40), default="")
    form: Mapped[str] = mapped_column(String(20))
    dose_units: Mapped[float] = mapped_column(Float, default=1)
    frequency: Mapped[str] = mapped_column(String(20))
    times: Mapped[str] = mapped_column(String(200), default="")
    weekdays: Mapped[str] = mapped_column(String(20), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    track_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    stock_units: Mapped[float] = mapped_column(Float, default=0)
    stock_total: Mapped[float] = mapped_column(Float, default=0)
    stock_set_at: Mapped[str | None] = mapped_column(String(32))  # momento da base de estoque (UTC)
    refill_alert_days: Mapped[int] = mapped_column(Integer, default=7)
    reminders: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)


class DoseLog(SyncMixin, Base):
    __tablename__ = "dose_logs"
    __table_args__ = (UniqueConstraint("medication_id", "scheduled_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20))
    acted_at: Mapped[datetime | None] = mapped_column(DateTime)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str] = mapped_column(Text, default="")
    taken_utc: Mapped[str | None] = mapped_column(String(32))  # quando virou "tomada" (desconta estoque)

    medication: Mapped[Medication] = relationship()


class WaterLog(SyncMixin, Base):
    __tablename__ = "water_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    amount_ml: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="copo")
    logged_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Contact(SyncMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    relation: Mapped[str] = mapped_column(String(80), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    is_doctor: Mapped[bool] = mapped_column(Boolean, default=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # dose_perdida | estoque_baixo | convite_aceito | ...
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class Device(Base):
    """Aparelho registrado para push (FCM/APNs)."""
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    token: Mapped[str] = mapped_column(String(400), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    event: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

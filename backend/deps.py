"""Dependências do FastAPI: sessão, usuário autenticado e controle de acesso por paciente."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import orm
from .adapters import PatientCore
from .config import Settings
from .security import decode_access_token


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request):
    yield from request.app.state.db.session()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def current_user(request: Request, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> orm.User:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    sub = decode_access_token(settings, token) if token else None
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão expirada ou inválida",
                            headers={"WWW-Authenticate": "Bearer"})
    user = db.scalar(select(orm.User).where(orm.User.uuid == sub))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Conta inexistente ou desativada")
    return user


@dataclass
class Access:
    user: orm.User
    patient: orm.Patient
    role: str        # owner | caregiver | doctor
    can_write: bool
    db: Session
    ip: str
    settings: Settings

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def core(self) -> PatientCore:
        return PatientCore(self.db, self.patient, self.user.id, self.ip, api_key=self.settings.anthropic_api_key,
                           read_only=not self.can_write)

    def require_write(self) -> None:
        if not self.can_write:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Você tem acesso somente leitura a este paciente")

    def require_owner(self) -> None:
        if not self.is_owner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Apenas o próprio paciente pode fazer isso")


def resolve_access(db: Session, user: orm.User, patient_uuid: str) -> tuple[orm.Patient, str, bool] | None:
    patient = db.scalar(select(orm.Patient).where(orm.Patient.uuid == patient_uuid))
    if patient is None:
        return None
    if patient.owner_user_id == user.id:
        return patient, "owner", True
    link = db.scalar(select(orm.CareLink).where(orm.CareLink.patient_id == patient.id,
                                                orm.CareLink.user_id == user.id))
    if link is None:
        return None
    return patient, link.role, link.can_edit


def patient_access(patient_id: str, request: Request, user: orm.User = Depends(current_user),
                   db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> Access:
    found = resolve_access(db, user, patient_id)
    if found is None:
        # 404 em vez de 403: não revela se o paciente existe
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Paciente não encontrado")
    patient, role, can_write = found
    return Access(user, patient, role, can_write, db, client_ip(request), settings)

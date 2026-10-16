"""Cadastro, login, renovação de sessão, troca de senha e sessão atual."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from medremind.core.repositories import utcnow_iso

from .. import orm, schemas
from ..config import Settings
from ..deps import client_ip, current_user, get_db, get_settings
from ..security import (
    create_access_token,
    hash_password,
    issue_refresh_token,
    password_problem,
    revoke_all,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(db: Session, settings: Settings, user: orm.User, request: Request) -> schemas.TokenOut:
    refresh = issue_refresh_token(db, settings, user, request.headers.get("user-agent", ""))
    return schemas.TokenOut(access_token=create_access_token(settings, user), refresh_token=refresh,
                            expires_in=settings.access_minutes * 60)


def _limit(request: Request, key: str) -> None:
    if not request.app.state.auth_limiter.hit(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Muitas tentativas. Aguarde alguns minutos.")


@router.post("/register", response_model=schemas.TokenOut, status_code=201)
def register(body: schemas.RegisterIn, request: Request, db: Session = Depends(get_db),
             settings: Settings = Depends(get_settings)):
    _limit(request, f"register:{client_ip(request)}")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)
    email = body.email.lower()
    if db.scalar(select(orm.User.id).where(func.lower(orm.User.email) == email)):
        raise HTTPException(409, "Já existe uma conta com este e-mail")
    user = orm.User(email=email, name=body.name.strip(), password_hash=hash_password(body.password),
                    account_type=body.account_type, professional_id=body.professional_id.strip(),
                    consent_at=orm.utcnow(), last_login_at=orm.utcnow())
    db.add(user)
    db.flush()
    patient = orm.Patient(owner_user_id=user.id, timezone=body.timezone or settings.default_timezone,
                          profile={"name": user.name, "email": email, "water_goal_ml": 2000},
                          profile_updated_at=utcnow_iso())
    db.add(patient)
    db.flush()
    db.add(orm.AuditEvent(patient_id=patient.id, user_id=user.id, event="conta_criada",
                          detail="termos aceitos (LGPD)", ip=client_ip(request)))
    return _tokens(db, settings, user, request)


@router.post("/login", response_model=schemas.TokenOut)
def login(body: schemas.LoginIn, request: Request, db: Session = Depends(get_db),
          settings: Settings = Depends(get_settings)):
    email = body.email.lower()
    _limit(request, f"login:{client_ip(request)}:{email}")
    user = db.scalar(select(orm.User).where(func.lower(orm.User.email) == email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        if user is not None and user.patient:
            db.add(orm.AuditEvent(patient_id=user.patient.id, user_id=user.id, event="login_falhou",
                                  ip=client_ip(request)))
            db.commit()  # a tentativa negada fica na auditoria
        raise HTTPException(401, "E-mail ou senha incorretos")
    request.app.state.auth_limiter.reset(f"login:{client_ip(request)}:{email}")
    user.last_login_at = orm.utcnow()
    if user.patient:
        db.add(orm.AuditEvent(patient_id=user.patient.id, user_id=user.id, event="login_ok", ip=client_ip(request)))
    return _tokens(db, settings, user, request)


@router.post("/refresh", response_model=schemas.TokenOut)
def refresh(body: schemas.RefreshIn, request: Request, db: Session = Depends(get_db),
            settings: Settings = Depends(get_settings)):
    rotated = rotate_refresh_token(db, settings, body.refresh_token, request.headers.get("user-agent", ""))
    if rotated is None:
        db.commit()  # mantém a revogação da família mesmo respondendo erro
        raise HTTPException(401, "Sessão expirada. Entre novamente.")
    user, new_refresh = rotated
    return schemas.TokenOut(access_token=create_access_token(settings, user), refresh_token=new_refresh,
                            expires_in=settings.access_minutes * 60)


@router.post("/logout", status_code=204)
def logout(body: schemas.RefreshIn, db: Session = Depends(get_db)):
    revoke_refresh_token(db, body.refresh_token)


@router.post("/logout-all", status_code=204)
def logout_all(user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    revoke_all(db, user.id)


@router.post("/change-password", status_code=204)
def change_password(body: schemas.ChangePasswordIn, user: orm.User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Senha atual incorreta")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = hash_password(body.new_password)
    revoke_all(db, user.id)  # derruba as outras sessões


@router.get("/me", response_model=schemas.UserOut)
def me(user: orm.User = Depends(current_user)):
    return schemas.UserOut(id=user.uuid, email=user.email, name=user.name, account_type=user.account_type,
                           patient_id=user.patient.uuid if user.patient else None)

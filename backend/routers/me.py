"""Conta do usuário: pacientes acessíveis, painel de acompanhamento, notificações,
aparelhos para push e direitos LGPD (exportar e excluir)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from medremind.core.models import DoseStatus

from .. import orm, schemas
from ..adapters import PatientCore
from ..deps import current_user, get_db
from ..security import verify_password
from ..sync_service import SyncService

router = APIRouter(prefix="/me", tags=["conta"])


def _patient_name(p: orm.Patient) -> str:
    return (p.profile or {}).get("name") or p.owner.name


def accessible(db: Session, user: orm.User) -> list[tuple[orm.Patient, str, bool]]:
    out = []
    if user.patient:
        out.append((user.patient, "owner", True))
    for link in db.scalars(select(orm.CareLink).where(orm.CareLink.user_id == user.id)):
        out.append((link.patient, link.role, link.can_edit))
    return out


@router.get("/patients", response_model=list[schemas.PatientSummary])
def my_patients(user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    return [schemas.PatientSummary(id=p.uuid, name=_patient_name(p), role=r, can_write=w)
            for p, r, w in accessible(db, user)]


@router.get("/dashboard")
def dashboard(user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    """Painel do cuidador/médico: todos os pacientes acompanhados com indicadores de risco."""
    rows = []
    for p, role, can_write in accessible(db, user):
        if role == "owner":
            continue
        core = PatientCore(db, p)
        today = core.clock().date()
        adh7 = core.schedule.adherence(today - timedelta(days=6), today)
        doses = core.schedule.doses_for_day(today)
        missed_today = sum(d.status == DoseStatus.MISSED for d in doses)
        low = [s.medication.display_name for s in core.meds.stock_overview() if s.low]
        last = db.scalar(select(func.max(orm.DoseLog.updated_at)).where(orm.DoseLog.patient_id == p.id))
        rate = adh7.rate if adh7.due else None
        risk = "alto" if (rate is not None and rate < 0.7) or missed_today >= 2 else \
            "medio" if (rate is not None and rate < 0.9) or missed_today or low else "baixo"
        rows.append({"patient_id": p.uuid, "name": _patient_name(p), "role": role, "can_write": can_write,
                     "adherence_7d": rate, "missed_today": missed_today,
                     "taken_today": sum(d.status == DoseStatus.TAKEN for d in doses), "planned_today": len(doses),
                     "low_stock": low, "last_activity": last, "risk": risk})
    order = {"alto": 0, "medio": 1, "baixo": 2}
    return sorted(rows, key=lambda r: (order[r["risk"]], r["name"]))


# ------------------------------------------------------------------ notificações
@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = Query(50, le=200),
                  user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(orm.Notification).where(orm.Notification.user_id == user.id)
    if unread_only:
        q = q.where(orm.Notification.read_at.is_(None))
    rows = db.scalars(q.order_by(orm.Notification.id.desc()).limit(limit)).all()
    unread = db.scalar(select(func.count()).select_from(orm.Notification)
                       .where(orm.Notification.user_id == user.id, orm.Notification.read_at.is_(None)))
    patients = {p.id: p.uuid for p, _, _ in accessible(db, user)}
    return {"unread": unread, "items": [
        {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "created_at": n.created_at,
         "read": n.read_at is not None, "patient_id": patients.get(n.patient_id)} for n in rows]}


@router.post("/notifications/read-all", status_code=204)
def read_all(user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(orm.Notification).where(orm.Notification.user_id == user.id,
                                              orm.Notification.read_at.is_(None)).values(read_at=orm.utcnow()))


@router.post("/notifications/{notification_id}/read", status_code=204)
def read_one(notification_id: int, user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(orm.Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Notificação não encontrada")
    n.read_at = n.read_at or orm.utcnow()


@router.post("/devices", status_code=201)
def register_device(body: schemas.DeviceIn, user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    dev = db.scalar(select(orm.Device).where(orm.Device.token == body.token))
    if dev is None:
        db.add(orm.Device(user_id=user.id, platform=body.platform, token=body.token))
    else:
        dev.user_id, dev.platform = user.id, body.platform  # aparelho trocou de dono
    return {"ok": True}


# -------------------------------------------------------------------------- LGPD
@router.get("/export")
def export(user: orm.User = Depends(current_user), db: Session = Depends(get_db)):
    """Portabilidade (LGPD art. 18, V): todos os dados do titular em JSON."""
    out = {"format": "medremind-export", "version": 1, "exported_at": orm.utcnow(),
           "account": {"email": user.email, "name": user.name, "account_type": user.account_type,
                       "created_at": user.created_at, "consent_at": user.consent_at}}
    if user.patient:
        p = user.patient
        out["patient"] = {"profile": p.profile, "timezone": p.timezone,
                          "data": SyncService(db, p, False).changes_since(0)}
        out["care_team"] = [{"name": l.user.name, "role": l.role, "can_edit": l.can_edit}
                            for l in db.scalars(select(orm.CareLink).where(orm.CareLink.patient_id == p.id))]
        out["audit"] = [{"event": e.event, "detail": e.detail, "at": e.created_at} for e in
                        db.scalars(select(orm.AuditEvent).where(orm.AuditEvent.patient_id == p.id)
                                   .order_by(orm.AuditEvent.id))]
    out["following"] = [{"patient": _patient_name(l.patient), "role": l.role}
                        for l in db.scalars(select(orm.CareLink).where(orm.CareLink.user_id == user.id))]
    return out


@router.delete("", status_code=204)
def delete_account(body: schemas.DeleteAccountIn, user: orm.User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Eliminação (LGPD art. 18, VI): apaga a conta, o paciente e todos os registros em cascata."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "Senha incorreta")
    if user.patient:
        pid = user.patient.id
        for model in (orm.DoseLog, orm.WaterLog, orm.Contact, orm.Medication, orm.CareLink, orm.Invite,
                      orm.Notification, orm.AuditEvent):
            db.query(model).filter(model.patient_id == pid).delete(synchronize_session=False)
    db.delete(user)

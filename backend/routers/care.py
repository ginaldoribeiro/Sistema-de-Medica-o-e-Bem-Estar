"""Equipe de cuidado: convites por código, vínculos de cuidadores e médicos."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import orm, schemas
from ..deps import Access, current_user, get_db, patient_access
from ..notifications import notify
from ..security import invite_code

router = APIRouter(tags=["equipe de cuidado"])

ROLE_LABEL = {"caregiver": "Cuidador(a)", "doctor": "Médico(a)", "owner": "Paciente"}


def _member(link: orm.CareLink) -> dict:
    return {"id": link.id, "user_id": link.user.uuid, "name": link.user.name, "email": link.user.email,
            "role": link.role, "role_label": ROLE_LABEL[link.role], "can_edit": link.can_edit,
            "notify_missed": link.notify_missed, "professional_id": link.user.professional_id,
            "since": link.created_at}


@router.get("/patients/{patient_id}/care-team")
def care_team(a: Access = Depends(patient_access)):
    links = a.db.scalars(select(orm.CareLink).where(orm.CareLink.patient_id == a.patient.id)
                         .order_by(orm.CareLink.created_at)).all()
    invites = []
    if a.is_owner:
        rows = a.db.scalars(select(orm.Invite).where(
            orm.Invite.patient_id == a.patient.id, orm.Invite.accepted_by.is_(None), orm.Invite.revoked.is_(False),
            orm.Invite.expires_at > orm.utcnow())).all()
        invites = [{"code": i.code, "role": i.role, "can_edit": i.can_edit, "expires_at": i.expires_at} for i in rows]
    owner = a.patient.owner
    return {"owner": {"name": owner.name, "email": owner.email},
            "members": [_member(l) for l in links], "pending_invites": invites,
            "my_role": a.role, "can_manage": a.is_owner}


@router.post("/patients/{patient_id}/invites", status_code=201)
def create_invite(body: schemas.InviteIn, a: Access = Depends(patient_access)):
    a.require_owner()
    for _ in range(5):
        code = invite_code()
        if not a.db.scalar(select(orm.Invite.id).where(orm.Invite.code == code)):
            break
    inv = orm.Invite(patient_id=a.patient.id, code=code, role=body.role, can_edit=body.can_edit,
                     created_by=a.user.id, expires_at=orm.utcnow() + timedelta(days=a.settings.invite_days))
    a.db.add(inv)
    a.db.add(orm.AuditEvent(patient_id=a.patient.id, user_id=a.user.id, event="convite_criado",
                            detail=f"{ROLE_LABEL[body.role]}{' com edição' if body.can_edit else ''}", ip=a.ip))
    return {"code": code, "role": body.role, "can_edit": body.can_edit, "expires_at": inv.expires_at}


@router.delete("/patients/{patient_id}/invites/{code}", status_code=204)
def revoke_invite(code: str, a: Access = Depends(patient_access)):
    a.require_owner()
    inv = a.db.scalar(select(orm.Invite).where(orm.Invite.code == code.upper(), orm.Invite.patient_id == a.patient.id))
    if inv:
        inv.revoked = True


@router.post("/invites/accept")
def accept_invite(body: schemas.AcceptInviteIn, request_user: orm.User = Depends(current_user),
                  db: Session = Depends(get_db)):
    inv = db.scalar(select(orm.Invite).where(orm.Invite.code == body.code.strip().upper().replace("-", "")))
    if inv is None or inv.revoked or inv.accepted_by is not None or inv.expires_at < orm.utcnow():
        raise HTTPException(404, "Código inválido ou expirado")
    patient = db.get(orm.Patient, inv.patient_id)
    if patient.owner_user_id == request_user.id:
        raise HTTPException(400, "Este convite é do seu próprio perfil")
    link = orm.CareLink(patient_id=patient.id, user_id=request_user.id, role=inv.role, can_edit=inv.can_edit)
    try:
        with db.begin_nested():
            db.add(link)
    except IntegrityError:
        raise HTTPException(409, "Você já faz parte da equipe deste paciente") from None
    inv.accepted_by, inv.accepted_at = request_user.id, orm.utcnow()
    db.add(orm.AuditEvent(patient_id=patient.id, user_id=request_user.id, event="convite_aceito",
                          detail=f"{request_user.name} ({ROLE_LABEL[inv.role]})"))
    notify(db, None, patient.owner_user_id, "convite_aceito", f"{request_user.name} entrou na sua equipe",
           f"Papel: {ROLE_LABEL[inv.role]}. Você pode remover o acesso quando quiser.", patient.id)
    return {"patient_id": patient.uuid, "patient_name": (patient.profile or {}).get("name") or patient.owner.name,
            "role": inv.role, "can_write": inv.can_edit}


@router.patch("/patients/{patient_id}/care-team/{member_id}")
def update_member(member_id: int, body: schemas.MemberUpdateIn, a: Access = Depends(patient_access)):
    link = a.db.get(orm.CareLink, member_id)
    if link is None or link.patient_id != a.patient.id:
        raise HTTPException(404, "Membro não encontrado")
    if body.can_edit is not None:
        a.require_owner()
        link.can_edit = body.can_edit
    if body.notify_missed is not None:
        if not (a.is_owner or link.user_id == a.user.id):
            raise HTTPException(403, "Sem permissão")
        link.notify_missed = body.notify_missed
    return _member(link)


@router.delete("/patients/{patient_id}/care-team/{member_id}", status_code=204)
def remove_member(member_id: int, a: Access = Depends(patient_access)):
    """O paciente remove alguém, ou o próprio membro sai da equipe."""
    link = a.db.get(orm.CareLink, member_id)
    if link is None or link.patient_id != a.patient.id:
        raise HTTPException(404, "Membro não encontrado")
    if not (a.is_owner or link.user_id == a.user.id):
        raise HTTPException(403, "Sem permissão")
    a.db.add(orm.AuditEvent(patient_id=a.patient.id, user_id=a.user.id, event="acesso_removido",
                            detail=link.user.name, ip=a.ip))
    a.db.delete(link)


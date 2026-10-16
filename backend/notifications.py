"""Notificações: caixa de entrada no servidor + push opcional (FCM) + varredura de alertas."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from medremind.core.models import DoseStatus

from . import orm
from .adapters import PatientCore
from .config import Settings

log = logging.getLogger("medremind.notify")


class PushSender:
    """Envia push via Firebase Cloud Messaging quando FCM_SERVER_KEY está definido; senão só registra em log."""

    def __init__(self, settings: Settings) -> None:
        self.key = settings.fcm_server_key

    def send(self, tokens: list[str], title: str, body: str) -> None:
        if not tokens:
            return
        if not self.key:
            log.info("push (simulado) para %d aparelho(s): %s", len(tokens), title)
            return
        try:
            import httpx

            httpx.post("https://fcm.googleapis.com/fcm/send", timeout=10,
                       headers={"Authorization": f"key={self.key}"},
                       json={"registration_ids": tokens, "notification": {"title": title, "body": body}})
        except Exception:  # push nunca derruba o fluxo principal
            log.exception("Falha ao enviar push")


def notify(db: Session, push: PushSender | None, user_id: int, kind: str, title: str, body: str = "",
           patient_id: int | None = None, dedupe_key: str | None = None) -> bool:
    """Cria a notificação (uma só vez por ``dedupe_key``) e dispara o push."""
    if dedupe_key and db.scalar(select(orm.Notification.id).where(orm.Notification.dedupe_key == dedupe_key)):
        return False
    try:
        with db.begin_nested():
            db.add(orm.Notification(user_id=user_id, patient_id=patient_id, kind=kind, title=title, body=body,
                                    dedupe_key=dedupe_key))
    except IntegrityError:
        return False
    if push:
        tokens = list(db.scalars(select(orm.Device.token).where(orm.Device.user_id == user_id)))
        push.send(tokens, title, body)
    return True


def scan_patient(db: Session, patient: orm.Patient, push: PushSender | None = None) -> int:
    """Gera alertas de um paciente: doses perdidas (para cuidadores) e estoque baixo (para todos)."""
    core = PatientCore(db, patient)
    today = core.clock().date()
    name = (patient.profile or {}).get("name") or patient.owner.name
    links = list(db.scalars(select(orm.CareLink).where(orm.CareLink.patient_id == patient.id)))
    created = 0

    for dose in core.schedule.doses_for_day(today):
        if dose.status != DoseStatus.MISSED:
            continue
        key = f"missed:{patient.uuid}:{dose.key}"
        for link in links:
            if link.notify_missed:
                created += notify(db, push, link.user_id, "dose_perdida", f"{name} não registrou uma dose",
                                  f"{dose.medication.display_name} das {dose.scheduled_at:%H:%M}",
                                  patient.id, f"{key}:{link.user_id}")

    for s in core.meds.stock_overview():
        if not s.low:
            continue
        msg = "acabou" if s.empty else f"acaba em ~{int(s.days_left)} dias" if s.days_left is not None else "está baixo"
        week = today - timedelta(days=today.weekday())
        key = f"stock:{patient.uuid}:{s.medication.id}:{week}"
        recipients = [patient.owner_user_id] + [l.user_id for l in links if l.role == "caregiver"]
        for uid in recipients:
            created += notify(db, push, uid, "estoque_baixo", f"{s.medication.display_name} {msg}",
                              f"Paciente: {name}. Providencie a reposição.", patient.id, f"{key}:{uid}")
    return created


def scan_all(db: Session, push: PushSender | None = None) -> int:
    total = 0
    for patient in db.scalars(select(orm.Patient)):
        try:
            total += scan_patient(db, patient, push)
        except Exception:
            log.exception("Falha na varredura do paciente %s", patient.uuid)
    return total

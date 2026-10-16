"""Recursos de um paciente: perfil, medicações, doses, água, contatos, métricas,
relatórios, assistente, auditoria e sincronização.

Toda rota passa por ``patient_access``: o dono tem acesso total; cuidadores e
médicos só entram se tiverem vínculo, e só escrevem com ``can_edit``.
"""
from __future__ import annotations

from datetime import date, timedelta

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select

from medremind.core.models import Contact, Medication, PlannedDose, Profile
from medremind.core.services.medications import ValidationError

from .. import orm, schemas
from ..deps import Access, patient_access
from ..sync_service import SyncService

router = APIRouter(prefix="/patients/{patient_id}", tags=["pacientes"])


def med_out(m: Medication, stock=None) -> dict:
    out = {
        "id": m.id, "name": m.name, "strength": m.strength, "display_name": m.display_name, "form": m.form.value,
        "dose_units": m.dose_units, "dose_text": m.dose_text, "frequency": m.frequency.value,
        "times": [t.strftime("%H:%M") for t in m.times], "weekdays": m.weekdays, "instructions": m.instructions,
        "start_date": m.start_date, "end_date": m.end_date, "track_stock": m.track_stock,
        "stock_units": m.stock_units, "stock_total": m.stock_total, "refill_alert_days": m.refill_alert_days,
        "reminders": m.reminders, "paused": m.paused,
    }
    if stock is not None:
        out["stock"] = {"days_left": None if stock.days_left is None else round(stock.days_left, 1),
                        "runs_out_on": stock.runs_out_on, "low": stock.low, "empty": stock.empty}
    return out


def dose_out(d: PlannedDose) -> dict:
    return {"medication_id": d.medication.id, "medication": d.medication.display_name,
            "instructions": d.medication.instructions, "scheduled_at": d.scheduled_at, "status": d.status.value,
            "status_label": d.status.label, "acted_at": d.acted_at, "snoozed_until": d.snoozed_until}


# ------------------------------------------------------------------------ perfil
@router.get("")
def overview(a: Access = Depends(patient_access)):
    """Resumo para a tela inicial: doses de hoje, próxima dose, meta, sequência e alertas."""
    core = a.core()
    doses = core.schedule.today()
    nxt = core.schedule.next_dose()
    taken = sum(d.status.value == "taken" for d in doses)
    water = core.hydration.today()
    return {
        "patient": {"id": a.patient.uuid, "name": (a.patient.profile or {}).get("name") or a.patient.owner.name,
                    "timezone": a.patient.timezone},
        "access": {"role": a.role, "can_write": a.can_write},
        "today": [dose_out(d) for d in doses],
        "progress": {"taken": taken, "planned": len(doses), "ratio": taken / len(doses) if doses else 1.0},
        "next_dose": dose_out(nxt) if nxt else None,
        "streak": core.schedule.streak(),
        "low_stock": [med_out(s.medication, s) for s in core.meds.stock_overview() if s.low],
        "water": {"total_ml": water.total_ml, "goal_ml": water.goal_ml},
    }


@router.get("/profile")
def get_profile(a: Access = Depends(patient_access)):
    return {"profile": a.patient.profile or {}, "updated_at": a.patient.profile_updated_at,
            "timezone": a.patient.timezone}


@router.put("/profile")
def put_profile(body: dict, a: Access = Depends(patient_access)):
    a.require_write()
    allowed = {"name", "birth_date", "email", "phone", "health_id", "blood_type", "allergies", "conditions",
               "pharmacy_name", "pharmacy_address", "water_goal_ml"}
    data = {**(a.patient.profile or {}), **{k: v for k, v in body.items() if k in allowed}}
    core = a.core()
    p = Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__})
    if isinstance(p.birth_date, str) and p.birth_date:
        p.birth_date = date.fromisoformat(p.birth_date)
    core.settings.save_profile(p)
    if "timezone" in body:
        try:
            ZoneInfo(body["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, "Fuso horário inválido") from None
        a.patient.timezone = body["timezone"]
    core.audit.log("perfil_editado", a.user.name)
    return get_profile(a)


# -------------------------------------------------------------------- medicações
@router.get("/medications")
def list_meds(a: Access = Depends(patient_access)):
    core = a.core()
    stock = {s.medication.id: s for s in core.meds.stock_overview()}
    return [med_out(m, stock.get(m.id)) for m in core.meds.list()]


def _save(core, m: Medication) -> Medication:
    try:
        return core.meds.save(m)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/medications", status_code=201)
def create_med(body: schemas.MedicationIn, a: Access = Depends(patient_access)):
    a.require_write()
    core = a.core()
    m = _save(core, Medication(**body.model_dump()))
    return med_out(m, core.meds.stock_status(m))


def _get_med(core, med_id: int) -> Medication:
    m = core.meds.get(med_id)
    if m is None:
        raise HTTPException(404, "Medicação não encontrada")
    return m


@router.get("/medications/{med_id}")
def get_med(med_id: int, a: Access = Depends(patient_access)):
    core = a.core()
    m = _get_med(core, med_id)
    return med_out(m, core.meds.stock_status(m))


@router.put("/medications/{med_id}")
def update_med(med_id: int, body: schemas.MedicationIn, a: Access = Depends(patient_access)):
    a.require_write()
    core = a.core()
    _get_med(core, med_id)
    m = Medication(**body.model_dump(), id=med_id)
    return med_out(_save(core, m), core.meds.stock_status(m))


@router.delete("/medications/{med_id}", status_code=204)
def delete_med(med_id: int, a: Access = Depends(patient_access)):
    a.require_write()
    core = a.core()
    _get_med(core, med_id)
    core.meds.delete(med_id)


@router.post("/medications/{med_id}/refill")
def refill(med_id: int, body: schemas.RefillIn, a: Access = Depends(patient_access)):
    a.require_write()
    core = a.core()
    _get_med(core, med_id)
    core.meds.refill(med_id, body.units)
    return get_med(med_id, a)


@router.post("/medications/{med_id}/pause")
def pause(med_id: int, paused: bool = True, a: Access = Depends(patient_access)):
    a.require_write()
    core = a.core()
    _get_med(core, med_id)
    core.meds.set_paused(med_id, paused)
    return get_med(med_id, a)


# ------------------------------------------------------------------------- doses
@router.get("/doses")
def doses(day: date | None = None, a: Access = Depends(patient_access)):
    core = a.core()
    return [dose_out(d) for d in core.schedule.doses_for_day(day or core.clock().date())]


@router.get("/doses/next")
def next_dose(a: Access = Depends(patient_access)):
    d = a.core().schedule.next_dose()
    return dose_out(d) if d else None


@router.post("/doses/action")
def dose_action(body: schemas.DoseActionIn, a: Access = Depends(patient_access)):
    """Idempotente: repetir "take" na mesma dose não desconta o estoque de novo."""
    a.require_write()
    core = a.core()
    _get_med(core, body.medication_id)
    at = body.scheduled_at.replace(tzinfo=None, second=0, microsecond=0)
    try:
        if body.action == "take":
            core.schedule.mark_taken(body.medication_id, at)
        elif body.action == "skip":
            core.schedule.skip(body.medication_id, at)
        elif body.action == "snooze":
            core.schedule.snooze(body.medication_id, at, body.minutes)
        else:
            core.schedule.undo(body.medication_id, at)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
    return [dose_out(d) for d in core.schedule.doses_for_day(at.date())]


# -------------------------------------------------------------------------- água
@router.get("/water")
def water(a: Access = Depends(patient_access)):
    day = a.core().hydration.today()
    return {"total_ml": day.total_ml, "goal_ml": day.goal_ml,
            "logs": [{"id": l.id, "amount_ml": l.amount_ml, "kind": l.kind, "logged_at": l.logged_at}
                     for l in day.logs]}


@router.post("/water", status_code=201)
def add_water(body: schemas.WaterIn, a: Access = Depends(patient_access)):
    a.require_write()
    a.core().hydration.add(body.amount_ml, body.kind)
    return water(a)


@router.delete("/water/{log_id}", status_code=204)
def delete_water(log_id: int, a: Access = Depends(patient_access)):
    a.require_write()
    a.core().hydration.repo.delete(log_id)


# ---------------------------------------------------------------------- contatos
@router.get("/contacts")
def contacts(a: Access = Depends(patient_access)):
    return [c.__dict__ for c in a.core().contacts.list()]


@router.post("/contacts", status_code=201)
def add_contact(body: schemas.ContactIn, a: Access = Depends(patient_access)):
    a.require_write()
    c = a.core().contacts.add(Contact(**body.model_dump()))
    return c.__dict__


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, a: Access = Depends(patient_access)):
    a.require_write()
    a.core().contacts.delete(contact_id)


# ---------------------------------------------------------------------- métricas
@router.get("/adherence")
def adherence(days: int = Query(30, ge=1, le=365), a: Access = Depends(patient_access)):
    core = a.core()
    end = core.clock().date()
    adh = core.schedule.adherence(end - timedelta(days=days - 1), end)
    return {"days": days, "due": adh.due, "taken": adh.taken, "on_time": adh.on_time,
            "rate": round(adh.rate, 4), "on_time_rate": round(adh.on_time_rate, 4),
            "streak": core.schedule.streak(),
            "weekly": [{"week_start": s, "rate": r} for s, r in core.schedule.weekly_adherence(4)]}


@router.get("/week")
def week(ref: date | None = None, a: Access = Depends(patient_access)):
    return [{"day": s.day, "state": s.state, "planned": s.planned, "taken": s.taken, "missed": s.missed}
            for s in a.core().schedule.week(ref)]


@router.get("/stock")
def stock(a: Access = Depends(patient_access)):
    return [med_out(s.medication, s) for s in a.core().meds.stock_overview()]


@router.get("/reports/doses.csv", response_class=PlainTextResponse)
def report_csv(days: int = Query(30, ge=1, le=365), a: Access = Depends(patient_access)):
    core = a.core()
    end = core.clock().date()
    core.audit.log("relatorio_gerado", f"CSV {days} dias por {a.user.name}")
    return PlainTextResponse(core.reports.csv_text(end - timedelta(days=days - 1), end),
                             headers={"Content-Disposition": "attachment; filename=medremind-doses.csv"})


@router.get("/reports/summary.html", response_class=HTMLResponse)
def report_html(days: int = Query(30, ge=1, le=365), a: Access = Depends(patient_access)):
    core = a.core()
    end = core.clock().date()
    core.audit.log("relatorio_gerado", f"HTML {days} dias por {a.user.name}")
    return core.reports.html_text(end - timedelta(days=days - 1), end)


# ------------------------------------------------------------------- assistente
@router.post("/assistant")
def ask(body: schemas.AskIn, a: Access = Depends(patient_access)):
    # Com acesso somente leitura, as ferramentas que gravam ficam bloqueadas (ver PatientCore).
    reply = a.core().assistant.reply(body.message)
    return {"reply": reply.text, "tools_used": reply.tools_used, "engine": reply.engine,
            "changed_data": reply.changed_data and a.can_write}


# -------------------------------------------------------------------- auditoria
@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=500), a: Access = Depends(patient_access)):
    a.require_owner()
    rows = a.db.execute(select(orm.AuditEvent, orm.User.name).outerjoin(orm.User, orm.User.id == orm.AuditEvent.user_id)
                        .where(orm.AuditEvent.patient_id == a.patient.id)
                        .order_by(orm.AuditEvent.id.desc()).limit(limit)).all()
    return [{"event": e.event, "detail": e.detail, "by": name, "ip": e.ip, "at": e.created_at} for e, name in rows]


# --------------------------------------------------------------- sincronização
@router.post("/sync")
def sync(body: schemas.SyncIn, a: Access = Depends(patient_access)):
    total = sum(len(v) for v in body.changes.values() if isinstance(v, list))
    if total > a.settings.max_sync_items:
        raise HTTPException(413, "Lote grande demais; envie em partes")
    svc = SyncService(a.db, a.patient, a.can_write)
    rejected, applied = svc.apply(body.changes)
    if applied:
        a.db.add(orm.AuditEvent(
            patient_id=a.patient.id, user_id=a.user.id, event="sincronizacao", detail=f"{applied} alterações",
            ip=a.ip))
    a.db.flush()
    return {"cursor": a.patient.sync_seq, "changes": svc.changes_since(body.cursor), "rejected": rejected,
            "access": {"role": a.role, "can_write": a.can_write}}

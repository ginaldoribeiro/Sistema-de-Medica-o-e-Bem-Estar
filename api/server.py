"""API REST opcional do MedRemind (FastAPI).

Expõe o mesmo núcleo do app para integrações — por exemplo, um painel do
médico ou um relógio inteligente. Protegida por token (variável
``MEDREMIND_API_TOKEN``); sem token configurado, a API recusa todas as chamadas.

    MEDREMIND_API_TOKEN=troque-isto uvicorn api.server:app --port 8000
"""
from __future__ import annotations

import hmac
import os
from datetime import date, datetime, time, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from medremind.core.container import Container
from medremind.core.models import Frequency, Medication, MedForm, PlannedDose
from medremind.core.services.medications import ValidationError


class MedicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    strength: str = ""
    form: MedForm = MedForm.COMPRIMIDO
    dose_units: float = Field(1, gt=0)
    frequency: Frequency = Frequency.DAILY
    times: list[time] = []
    weekdays: list[int] = []
    instructions: str = ""
    track_stock: bool = True
    stock_units: float = Field(0, ge=0)
    refill_alert_days: int = Field(7, ge=0)


class DoseAction(BaseModel):
    medication_id: int
    scheduled_at: datetime


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


def _med_out(m: Medication) -> dict:
    return {
        "id": m.id, "name": m.name, "strength": m.strength, "form": m.form.value, "dose": m.dose_text,
        "frequency": m.frequency.value, "times": [t.strftime("%H:%M") for t in m.times], "weekdays": m.weekdays,
        "instructions": m.instructions, "stock_units": m.stock_units if m.track_stock else None, "paused": m.paused,
    }


def _dose_out(d: PlannedDose) -> dict:
    return {"medication_id": d.medication.id, "medication": d.medication.display_name,
            "scheduled_at": d.scheduled_at.isoformat(), "status": d.status.value,
            "acted_at": d.acted_at.isoformat() if d.acted_at else None}


def create_app(container: Container | None = None, token: str | None = None) -> FastAPI:
    c = container or Container.build()
    expected = token if token is not None else os.environ.get("MEDREMIND_API_TOKEN", "")
    app = FastAPI(title="MedRemind API", version="1.0.0")

    def auth(authorization: str = Header(default="")) -> None:
        given = authorization.removeprefix("Bearer ").strip()
        if not expected or not hmac.compare_digest(given, expected):
            raise HTTPException(401, "Token inválido ou API desativada")

    secured = [Depends(auth)]

    @app.get("/health")
    def health():
        return {"status": "ok", "schema": c.db.version}

    @app.get("/medications", dependencies=secured)
    def list_meds():
        return [_med_out(m) for m in c.meds.list()]

    @app.post("/medications", status_code=201, dependencies=secured)
    def create_med(body: MedicationIn):
        m = Medication(**body.model_dump())
        m.stock_total = m.stock_units
        try:
            c.meds.save(m)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        return _med_out(m)

    @app.get("/doses/today", dependencies=secured)
    def today():
        return [_dose_out(d) for d in c.schedule.today()]

    @app.post("/doses/take", dependencies=secured)
    def take(body: DoseAction):
        try:
            c.schedule.mark_taken(body.medication_id, body.scheduled_at)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        c.audit.log("api_acesso", "registro de dose")
        return {"ok": True}

    @app.get("/adherence", dependencies=secured)
    def adherence(days: int = 30):
        end = c.schedule.clock().date()
        a = c.schedule.adherence(end - timedelta(days=max(1, days) - 1), end)
        return {"days": days, "due": a.due, "taken": a.taken, "rate": round(a.rate, 4),
                "on_time_rate": round(a.on_time_rate, 4), "streak": c.schedule.streak()}

    @app.get("/stock", dependencies=secured)
    def stock():
        return [{"medication": s.medication.display_name, "units": s.medication.stock_units,
                 "days_left": None if s.days_left is None else round(s.days_left, 1), "low": s.low}
                for s in c.meds.stock_overview()]

    @app.get("/report.csv", response_class=PlainTextResponse, dependencies=secured)
    def report_csv(start: date | None = None, end: date | None = None):
        end = end or c.schedule.clock().date()
        c.audit.log("api_acesso", "relatório CSV")
        return c.reports.csv_text(start or end - timedelta(days=29), end)

    @app.get("/report.html", response_class=HTMLResponse, dependencies=secured)
    def report_html(days: int = 30):
        end = c.schedule.clock().date()
        c.audit.log("api_acesso", "relatório HTML")
        return c.reports.html_text(end - timedelta(days=days - 1), end)

    @app.post("/assistant", dependencies=secured)
    def ask(body: AskIn):
        r = c.assistant.reply(body.message)
        return {"reply": r.text, "tools_used": r.tools_used, "engine": r.engine}

    return app


app = create_app() if os.environ.get("MEDREMIND_API_AUTOSTART", "1") == "1" else None

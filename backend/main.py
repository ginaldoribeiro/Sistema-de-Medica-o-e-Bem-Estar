"""Aplicação FastAPI do MedRemind.

    uvicorn backend.main:app_factory --factory --reload   # desenvolvimento (SQLite)
    docker compose up                            # produção local (PostgreSQL)

Documentação interativa em /docs (Swagger) e /redoc.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import Settings
from .db import DB
from .notifications import PushSender, scan_all
from .ratelimit import make_limiter
from .routers import auth, care, me, patients

log = logging.getLogger("medremind.api")
API_PREFIX = "/api/v1"


async def _scheduler(app: FastAPI) -> None:
    """Varredura periódica de alertas (doses perdidas, estoque baixo)."""
    settings: Settings = app.state.settings
    push = PushSender(settings)
    while True:
        await asyncio.sleep(settings.scheduler_interval_s)
        try:
            def run():
                with app.state.db.Session() as s, s.begin():
                    return scan_all(s, push)
            created = await asyncio.to_thread(run)
            if created:
                log.info("Varredura de alertas: %d notificações criadas", created)
        except Exception:
            log.exception("Falha na varredura de alertas")


def create_app(settings: Settings | None = None, db: DB | None = None) -> FastAPI:
    settings = settings or Settings()
    db = db or DB(settings.database_url)
    if settings.is_sqlite:
        db.create_all()  # em PostgreSQL o schema vem das migrações do Alembic

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_scheduler(app)) if settings.scheduler_enabled else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="MedRemind API", version="2.0.0", lifespan=lifespan,
                  description="Backend do MedRemind: contas, equipe de cuidado, sincronização, alertas e relatórios.")
    app.state.settings = settings
    app.state.db = db
    app.state.auth_limiter = make_limiter(settings.redis_url, limit=10, window_s=300)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"  # dados de saúde não ficam em cache intermediário
        if settings.env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code, ms, rid)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:])
        msg = first.get("msg", "Dados inválidos").replace("Value error, ", "")
        errors = [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": f"{field}: {msg}" if field else msg, "errors": errors})

    @app.get("/health", tags=["infra"])
    def health():
        return {"status": "ok", "version": app.version}

    @app.get("/ready", tags=["infra"])
    def ready():
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "database unavailable"})
        return {"status": "ready"}

    for r in (auth.router, me.router, patients.router, care.router):
        app.include_router(r, prefix=API_PREFIX)
    return app


def app_factory() -> FastAPI:
    """Ponto de entrada do uvicorn: ``uvicorn backend.main:app_factory --factory``."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()

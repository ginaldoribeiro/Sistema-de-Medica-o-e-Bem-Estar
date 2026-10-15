"""Trilha de auditoria: registra acessos e alterações relevantes."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from ..models import AuditEntry
from ..repositories import AuditRepository

EVENT_LABELS = {
    "app_aberto": "App aberto",
    "login_ok": "Acesso liberado",
    "login_falhou": "Tentativa de acesso negada",
    "pin_definido": "PIN definido",
    "pin_removido": "PIN removido",
    "medicacao_criada": "Medicação adicionada",
    "medicacao_editada": "Medicação editada",
    "medicacao_removida": "Medicação removida",
    "dose_tomada": "Dose registrada",
    "dose_pulada": "Dose pulada",
    "dose_adiada": "Dose adiada",
    "registro_desfeito": "Registro desfeito",
    "estoque_reposto": "Estoque reposto",
    "backup_exportado": "Backup exportado",
    "backup_importado": "Backup restaurado",
    "relatorio_gerado": "Relatório gerado",
    "consentimento": "Termos aceitos",
    "api_acesso": "Acesso pela API",
}


class AuditService:
    def __init__(self, repo: AuditRepository, clock: Callable[[], datetime] = datetime.now) -> None:
        self.repo = repo
        self.clock = clock

    def log(self, event: str, detail: str = "") -> None:
        self.repo.add(event, detail, self.clock())

    def recent(self, limit: int = 50) -> list[AuditEntry]:
        return self.repo.recent(limit)

    @staticmethod
    def label(event: str) -> str:
        return EVENT_LABELS.get(event, event.replace("_", " ").capitalize())

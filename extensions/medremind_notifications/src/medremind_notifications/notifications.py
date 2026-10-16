from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from flet.controls.base_control import control
from flet.controls.services.service import Service


@dataclass
class ScheduledReminder:
    id: int            # inteiro estável (o sistema substitui avisos com o mesmo id)
    title: str
    body: str
    at: str            # data e hora local, ISO 8601 sem fuso: "2026-10-16T20:00:00"
    payload: str = ""  # devolvido ao app quando o usuário toca no aviso

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "body": self.body, "at": self.at, "payload": self.payload}


@control("MedRemindNotifications")
class MedRemindNotifications(Service):
    """Serviço Flet que conversa com o lado Dart (flutter_local_notifications)."""

    channel_name: Optional[str] = "Lembretes de remédios"
    channel_description: Optional[str] = "Avisos no horário de cada dose"

    async def request_permission(self) -> bool:
        """Pede permissão de notificação (Android 13+, iOS) e de alarme exato (Android 12+)."""
        return bool(await self._invoke_method("request_permission", timeout=30))

    async def replace_all(self, reminders: list[ScheduledReminder]) -> int:
        """Cancela os avisos agendados e agenda a nova lista. Devolve quantos foram agendados."""
        return int(await self._invoke_method(
            "replace_all", {"items": [r.to_dict() for r in reminders]}, timeout=30) or 0)

    async def cancel_all(self) -> None:
        await self._invoke_method("cancel_all", timeout=10)

    async def pending_count(self) -> int:
        return int(await self._invoke_method("pending_count", timeout=10) or 0)

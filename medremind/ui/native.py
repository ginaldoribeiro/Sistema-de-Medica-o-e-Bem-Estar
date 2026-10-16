"""Recursos nativos do aparelho: biometria e lembretes agendados no sistema.

Os dois dependem de extensões Flet que só existem no app compilado com
``flet build`` (Android/iOS/macOS/Windows). Em qualquer outro cenário — web,
Linux, desenvolvimento com ``python main.py`` — tudo aqui responde
"indisponível" sem quebrar o app, que segue com PIN e lembretes internos.
"""
from __future__ import annotations

import asyncio
import logging

import flet as ft

log = logging.getLogger("medremind.native")

BIOMETRIC_PLATFORMS = {ft.PagePlatform.ANDROID, ft.PagePlatform.IOS, ft.PagePlatform.MACOS, ft.PagePlatform.WINDOWS}
NOTIFY_PLATFORMS = {ft.PagePlatform.ANDROID, ft.PagePlatform.IOS, ft.PagePlatform.MACOS}
TIMEOUT_S = 8


class Native:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._auth = None
        self._notif = None
        self._auth_ok: bool | None = None
        self._notif_ok: bool | None = None
        web = bool(getattr(page, "web", False))
        platform = getattr(page, "platform", None)
        if not web and platform in BIOMETRIC_PLATFORMS:
            try:
                from flet_local_auth import LocalAuthentication

                self._auth = LocalAuthentication()
            except Exception:  # extensão não instalada
                log.info("Biometria indisponível (flet-local-auth ausente)")
        if not web and platform in NOTIFY_PLATFORMS:
            try:
                from medremind_notifications import MedRemindNotifications

                self._notif = MedRemindNotifications()
            except Exception:
                log.info("Lembretes do sistema indisponíveis (extensão ausente)")

    # ------------------------------------------------------------ biometria
    async def biometrics_available(self) -> bool:
        if self._auth is None:
            return False
        if self._auth_ok is None:
            try:
                self._auth_ok = bool(await asyncio.wait_for(self._auth.is_device_supported(), TIMEOUT_S)) and \
                    bool(await asyncio.wait_for(self._auth.can_check_biometrics(), TIMEOUT_S))
            except Exception:  # extensão não compilada no app, timeout, sem hardware...
                self._auth_ok = False
        return self._auth_ok

    async def authenticate(self, reason: str = "Desbloquear o MedRemind") -> bool:
        if not await self.biometrics_available():
            return False
        try:
            return bool(await self._auth.authenticate(reason, persist_across_backgrounding=True))
        except Exception as exc:  # cancelado, bloqueado, sem digital cadastrada
            log.info("Biometria não concluída: %s", exc)
            return False

    # ------------------------------------------------- lembretes no sistema
    @property
    def can_schedule(self) -> bool:
        return self._notif is not None and self._notif_ok is not False

    async def request_notification_permission(self) -> bool:
        if self._notif is None:
            return False
        try:
            self._notif_ok = await asyncio.wait_for(self._notif.request_permission(), 40)
        except Exception:
            self._notif_ok = False
        return bool(self._notif_ok)

    async def schedule(self, reminders) -> int:
        """Substitui os avisos agendados pela lista dada (``PlannedReminder``)."""
        if not self.can_schedule:
            return 0
        from medremind_notifications import ScheduledReminder

        items = [ScheduledReminder(r.id, r.title, r.body, r.at.isoformat(timespec="seconds"), r.payload)
                 for r in reminders]
        try:
            return await asyncio.wait_for(self._notif.replace_all(items), 30)
        except Exception as exc:
            log.info("Não foi possível agendar lembretes no sistema: %s", exc)
            self._notif_ok = False
            return 0

    async def cancel_all(self) -> None:
        if self._notif is not None:
            try:
                await asyncio.wait_for(self._notif.cancel_all(), 10)
            except Exception:
                pass

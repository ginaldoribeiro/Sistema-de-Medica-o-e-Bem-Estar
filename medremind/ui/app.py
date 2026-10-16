"""Shell do aplicativo: navegação, diálogos, lembretes e ciclo de vida."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Callable

import flet as ft

from ..client.session import CloudSession
from ..core.container import Container
from ..core.models import DoseStatus, PlannedDose
from . import theme as th
from .components import T, primary_button, secondary_button

log = logging.getLogger("medremind")

ViewResult = ft.Control | tuple[ft.Control, ft.Control | None]
ViewBuilder = Callable[..., ViewResult]

TABS = [
    ("home", "Início", ft.Icons.HOME_OUTLINED, ft.Icons.HOME),
    ("meds", "Remédios", ft.Icons.MEDICATION_OUTLINED, ft.Icons.MEDICATION),
    ("history", "Histórico", ft.Icons.HISTORY, ft.Icons.HISTORY),
    ("profile", "Perfil", ft.Icons.PERSON_OUTLINE, ft.Icons.PERSON),
]
REMINDER_INTERVAL_S = 30
SYNC_INTERVAL_S = 30          # sincroniza pelo menos a cada 30 s com sessão ativa
TICK_S = 5                    # o laço acorda a cada 5 s para lembretes, sync e notificações
NOTIFY_POLL_S = 60
# Telas que podem ser redesenhadas quando chegam dados de outro aparelho (formulários não).
LIVE_ROUTES = {"home", "meds", "history", "stock", "hydration", "profile", "patients", "notifications", "care"}


class MedRemindApp:
    def __init__(self, page: ft.Page, device: Container, session: CloudSession | None = None) -> None:
        self.page = page
        self.device = device            # dados do aparelho: boas-vindas, consentimento, PIN, modo offline
        self.session = session          # conta na nuvem (opcional)
        self.routes: dict[str, ViewBuilder] = {}
        self.stack: list[tuple[str, dict]] = []
        self.unlocked = False
        self.unread = 0
        self.last_sync = None
        self._reminder_task = None
        self._syncing = False
        self._sync_due = 0.0
        self._register_routes()

    # -------------------------------------------------------------- dados ativos
    @property
    def cloud(self) -> bool:
        return bool(self.session and self.session.logged_in and self.session.patients)

    @property
    def c(self) -> Container:
        """Container do paciente em foco: o cache dele (nuvem) ou o banco do aparelho (offline)."""
        return self.session.container() if self.cloud else self.device

    @property
    def patient(self):
        return self.session.active if self.cloud else None

    @property
    def read_only(self) -> bool:
        return bool(self.cloud and self.patient and not self.patient.can_write)

    def guard_write(self) -> bool:
        """Chame antes de gravar. Devolve False (e avisa) se o acesso for somente leitura."""
        if self.read_only:
            self.toast(f"Acesso somente leitura aos dados de {self.patient.name}.")
            return False
        return True

    def switch_patient(self, patient_id: str) -> None:
        ref = self.session.switch(patient_id)
        self.toast(f"Vendo os dados de {ref.name}" if ref.role != "owner" else "Vendo os seus dados")
        self.go("home", reset=True)
        self.request_sync()

    def request_sync(self) -> None:
        self._sync_due = 0.0

    # ------------------------------------------------------------------ setup
    def _register_routes(self) -> None:
        from .views import account, assistant, home, meds, onboarding, profile, tracking

        self.routes.update({
            "onboarding": onboarding.onboarding_view,
            "consent": onboarding.consent_view,
            "lock": onboarding.lock_view,
            "pin_setup": onboarding.pin_setup_view,
            "home": home.home_view,
            "meds": meds.meds_view,
            "med_form": meds.med_form_view,
            "history": tracking.history_view,
            "stock": tracking.stock_view,
            "hydration": tracking.hydration_view,
            "profile": profile.profile_view,
            "reports": profile.reports_view,
            "backup": profile.backup_view,
            "audit": profile.audit_view,
            "assistant": assistant.assistant_view,
            "emergency": assistant.emergency_view,
            "account": account.account_view,
            "care": account.care_view,
            "patients": account.patients_view,
            "notifications": account.notifications_view,
        })

    def start(self) -> None:
        p = self.page
        p.title = "MedRemind"
        p.fonts = th.FONTS
        p.theme = th.theme()
        p.theme_mode = ft.ThemeMode.LIGHT
        p.bgcolor = th.BG
        p.padding = 0
        p.spacing = 0
        self.device.audit.log("app_aberto")
        if not self.device.onboarded:
            self.go("onboarding", replace=True)
        elif not self.device.consent_given:
            self.go("consent", replace=True)
        elif self.session and not self.session.logged_in and not self.device.settings.get("mode"):
            self.go("account", replace=True, first_run=True)
        elif self.device.security.has_pin:
            self.go("lock", replace=True)
        else:
            self.unlock()

    def unlock(self) -> None:
        self.unlocked = True
        # MEDREMIND_START_ROUTE abre direto numa tela (útil em desenvolvimento e capturas).
        default = "patients" if self.cloud and self.session.is_professional and self.session.follows_others else "home"
        start = os.environ.get("MEDREMIND_START_ROUTE", default)
        self.go(start if start in self.routes else "home", replace=True, reset=True)
        if self._reminder_task is None:
            self._reminder_task = self.page.run_task(self._reminder_loop)

    def lock(self) -> None:
        if self.device.security.has_pin:
            self.unlocked = False
            self.go("lock", replace=True, reset=True)

    # ------------------------------------------------------------- navegação
    @property
    def route(self) -> str:
        return self.stack[-1][0] if self.stack else ""

    def go(self, name: str, replace: bool = False, reset: bool = False, **params) -> None:
        if name not in self.routes:
            raise KeyError(name)
        if reset:
            self.stack.clear()
        if name in {t[0] for t in TABS}:
            # Abas são raízes de navegação: trocar de aba limpa a pilha.
            self.stack.clear()
        if replace and self.stack:
            self.stack[-1] = (name, params)
        else:
            self.stack.append((name, params))
        self.render()

    def back(self, *_):
        if len(self.stack) > 1:
            self.stack.pop()
            self.render()
        else:
            self.go("home", reset=True)

    def refresh(self, *_):
        self.render()

    def render(self) -> None:
        name, params = self.stack[-1]
        try:
            result = self.routes[name](self, **params)
        except Exception:  # nunca deixar o usuário numa tela em branco
            log.exception("Erro ao montar a tela %s", name)
            result = ft.Column([T("Algo deu errado ao abrir esta tela.", 16, 700),
                                primary_button("Voltar ao início", lambda e: self.go("home", reset=True))],
                               spacing=16)
        body, fab = result if isinstance(result, tuple) else (result, None)
        p = self.page
        p.controls.clear()
        p.add(ft.SafeArea(body, expand=True))
        tab_names = [t[0] for t in TABS]
        p.navigation_bar = self._nav_bar(tab_names.index(name)) if name in tab_names else None
        p.floating_action_button = fab
        p.update()

    def _nav_bar(self, index: int) -> ft.NavigationBar:
        return ft.NavigationBar(
            selected_index=index,
            bgcolor=th.SURFACE,
            indicator_color=th.PRIMARY_TINT,
            elevation=0,
            border=ft.Border.only(top=ft.BorderSide(1, th.LINE)),
            destinations=[ft.NavigationBarDestination(icon=i, selected_icon=si, label=l) for _, l, i, si in TABS],
            on_change=lambda e: self.go(TABS[e.control.selected_index][0], reset=True),
        )

    def screen(self, header: ft.Control | None, children: list[ft.Control], gap: float = 16,
               bottom: float = 28) -> ft.Column:
        """Corpo rolável padrão: cabeçalho + conteúdo com margens laterais."""
        content = ft.Container(ft.Column(children, spacing=gap),
                               padding=ft.Padding.only(left=th.GUTTER, right=th.GUTTER, top=12, bottom=bottom))
        return ft.Column(([header] if header else []) + [content], scroll=ft.ScrollMode.AUTO, expand=True, spacing=0)

    # ------------------------------------------------------- feedback e diálogos
    def toast(self, message: str, action: str | None = None, on_action: Callable | None = None) -> None:
        sb = ft.SnackBar(T(message, 14, 600, "#FFFFFF"), bgcolor=th.INK, behavior=ft.SnackBarBehavior.FLOATING,
                         action=action, on_action=on_action, duration=3500)
        self.page.show_dialog(sb)

    def close_dialog(self, *_):
        try:
            self.page.pop_dialog()
        except Exception:
            pass

    def confirm(self, title: str, text: str, on_yes: Callable[[], None], yes: str = "Confirmar",
                danger: bool = False) -> None:
        def yes_click(e):
            self.close_dialog()
            on_yes()
        self.page.show_dialog(ft.AlertDialog(
            title=T(title, 19, 800), content=T(text, 15, 400, th.INK_2), bgcolor=th.SURFACE,
            actions=[ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=self.close_dialog),
                     ft.TextButton(content=T(yes, 14, 800, th.DANGER if danger else th.PRIMARY), on_click=yes_click)],
        ))

    def dialog(self, title: str, content: ft.Control, actions: list[ft.Control]) -> None:
        self.page.show_dialog(ft.AlertDialog(title=T(title, 19, 800), content=content, actions=actions,
                                             bgcolor=th.SURFACE, scrollable=True))

    # ------------------------------------------------------------ ações de dose
    def dose_actions(self, dose: PlannedDose) -> None:
        """Folha inferior com as ações possíveis para uma dose."""
        med = dose.medication
        sheet: ft.BottomSheet | None = None

        def run(fn, msg):
            def handler(e):
                if not self.guard_write():
                    self.page.pop_dialog()
                    return
                fn()
                self.page.pop_dialog()
                self.toast(msg)
                self.refresh()
            return handler

        buttons: list[ft.Control] = []
        if dose.status != DoseStatus.TAKEN:
            buttons.append(primary_button("Tomei agora", run(lambda: self.c.schedule.mark_taken(med.id, dose.scheduled_at),
                                                               f"{med.display_name} registrado"), ft.Icons.CHECK))
        if dose.status in (DoseStatus.DUE, DoseStatus.UPCOMING, DoseStatus.SNOOZED):
            buttons.append(secondary_button("Adiar 10 minutos", run(lambda: self.c.schedule.snooze(med.id, dose.scheduled_at, 10),
                                                                    "Lembrete adiado por 10 min"), ft.Icons.SNOOZE))
        if dose.status not in (DoseStatus.SKIPPED, DoseStatus.TAKEN):
            buttons.append(secondary_button("Pular esta dose", run(lambda: self.c.schedule.skip(med.id, dose.scheduled_at),
                                                                   "Dose marcada como pulada"), ft.Icons.REDO))
        if dose.status in (DoseStatus.TAKEN, DoseStatus.SKIPPED, DoseStatus.SNOOZED):
            buttons.append(secondary_button("Desfazer registro", run(lambda: self.c.schedule.undo(med.id, dose.scheduled_at),
                                                                     "Registro desfeito"), ft.Icons.UNDO))
        info = f"{dose.scheduled_at:%H:%M} · {dose.status.label}"
        if dose.acted_at and dose.status == DoseStatus.TAKEN:
            info += f" às {dose.acted_at:%H:%M}"
        sheet = ft.BottomSheet(
            ft.Container(ft.Column([
                T(med.display_name, 20, 800),
                T(info + (f"\n{med.instructions}" if med.instructions else ""), 14, 500, th.INK_2),
                ft.Container(height=4),
                *[ft.Row([b]) for b in buttons],
            ], spacing=10, tight=True), padding=ft.Padding.only(left=20, right=20, top=8, bottom=28)),
            bgcolor=th.SURFACE, show_drag_handle=True,
        )
        self.page.show_dialog(sheet)

    # ---------------------------------------------------------------- lembretes
    async def _reminder_loop(self) -> None:
        """Laço de fundo: lembretes (30 s), sincronização (30 s ou logo após mudanças) e notificações."""
        loop = asyncio.get_running_loop()
        next_reminder = next_notify = 0.0
        self._sync_due = 0.0
        while True:
            now = loop.time()
            try:
                own = not self.cloud or self.patient.role == "owner"  # lembretes só dos próprios remédios
                if self.unlocked and own and now >= next_reminder:
                    next_reminder = now + REMINDER_INTERVAL_S
                    for r in self.c.reminders.poll():
                        self._show_reminder(r.dose, r.repeat)
                if self.unlocked and self.cloud and not self._syncing:
                    pending = await asyncio.to_thread(self.session.pending)
                    if pending and self._sync_due > now + 3:
                        self._sync_due = now + 3  # mudança local: sobe em poucos segundos
                    if now >= self._sync_due:
                        self._sync_due = now + SYNC_INTERVAL_S
                        await self._run_sync()
                    if now >= next_notify:
                        next_notify = now + NOTIFY_POLL_S
                        await self._poll_notifications()
            except Exception:
                log.exception("Falha no laço de fundo")
            await asyncio.sleep(TICK_S)

    async def _run_sync(self, manual: bool = False):
        self._syncing = True
        try:
            result = await asyncio.to_thread(self.session.sync)
        finally:
            self._syncing = False
        self.last_sync = result
        if result.ok and result.rejected:
            self.toast(f"{len(result.rejected)} alteração(ões) recusada(s) pelo servidor e desfeita(s).")
        if manual:
            self.toast("Sincronizado" if result.ok else result.error)
        if (result.ok and result.pulled and self.route in LIVE_ROUTES) or manual:
            self.refresh()
        return result

    async def _poll_notifications(self) -> None:
        try:
            data = await asyncio.to_thread(self.session.api.notifications, True)
        except Exception:
            return
        if data["unread"] != self.unread:
            new = data["unread"] > self.unread
            self.unread = data["unread"]
            if new and data["items"]:
                self.toast(data["items"][0]["title"], "Ver", lambda e: self.go("notifications"))
            if self.route in ("home", "profile"):
                self.refresh()

    def sync_now(self, *_):
        if self.cloud:
            self.page.run_task(self._run_sync, True)

    def _show_reminder(self, dose: PlannedDose, repeat: bool) -> None:
        med = dose.medication

        def act(fn, msg):
            def handler(e):
                fn()
                self.close_dialog()
                self.toast(msg)
                self.refresh()
            return handler

        self.page.show_dialog(ft.AlertDialog(
            modal=True, bgcolor=th.SURFACE,
            icon=ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE, color=th.PRIMARY, size=36),
            title=T(("Lembrete: " if repeat else "") + "hora do remédio", 20, 800, text_align=ft.TextAlign.CENTER),
            content=T(f"{med.display_name} · {dose.scheduled_at:%H:%M}"
                      + (f"\n{med.instructions}" if med.instructions else ""), 16, 500, th.INK_2,
                      text_align=ft.TextAlign.CENTER),
            actions=[ft.Column([
                ft.Row([primary_button("Tomei", act(lambda: self.c.schedule.mark_taken(med.id, dose.scheduled_at),
                                                   "Dose registrada"), ft.Icons.CHECK)]),
                ft.Row([secondary_button("Adiar 10 min", act(lambda: self.c.schedule.snooze(med.id, dose.scheduled_at, 10),
                                                            "Vou lembrar em 10 min"), height=48),
                        secondary_button("Pular", act(lambda: self.c.schedule.skip(med.id, dose.scheduled_at),
                                                      "Dose pulada"), height=48)], spacing=8),
            ], spacing=8, tight=True)],
        ))
        _desktop_notify(f"Hora do remédio: {med.display_name}", med.instructions or f"Dose das {dose.scheduled_at:%H:%M}")


def _desktop_notify(title: str, body: str) -> None:
    """Notificação do sistema quando rodando no desktop (opcional: pip install plyer)."""
    try:
        from plyer import notification  # type: ignore

        notification.notify(title=title, message=body, app_name="MedRemind", timeout=10)
    except Exception:
        pass


def greeting(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    return "Bom dia" if 5 <= h < 12 else "Boa tarde" if 12 <= h < 18 else "Boa noite"

"""Tela inicial: meta do dia, próxima dose, atalhos e programação de hoje."""
from __future__ import annotations

import flet as ft

from ...core.models import DoseStatus
from .. import theme as th
from ..app import greeting
from ..components import (
    T,
    avatar,
    card,
    icon_badge,
    initials,
    section,
    status_badge,
    status_chip,
)


def _ring(ratio: float) -> ft.Stack:
    return ft.Stack([
        ft.ProgressRing(value=ratio, width=100, height=100, stroke_width=10, color=th.SUCCESS,
                        bgcolor=th.SURFACE_2, stroke_cap=ft.StrokeCap.ROUND),
        ft.Container(T(f"{ratio:.0%}", 22, 800), width=100, height=100, alignment=ft.Alignment.CENTER),
    ], width=100, height=100)


def _next_dose_card(app, dose) -> ft.Control:
    if dose is None:
        return card(ft.Row([icon_badge(ft.Icons.CHECK, th.SUCCESS, "#FFFFFF", size=48, radius=16),
                            ft.Column([T("Tudo em dia", 16, 800, th.SUCCESS_INK),
                                       T("Nenhuma dose pendente por agora.", 14, 500, th.SUCCESS_INK)],
                                      spacing=2, expand=True)], spacing=14),
                    bg=th.SUCCESS_TINT, radius=26, padding=20)
    med = dose.medication
    now = app.c.schedule.clock()
    when = dose.snoozed_until or dose.scheduled_at
    if dose.status == DoseStatus.DUE:
        eta = "agora"
    else:
        mins = int((when - now).total_seconds() // 60)
        eta = f"em {mins} min" if mins < 60 else f"em {mins // 60} h {mins % 60:02d}" if mins < 24 * 60 else f"{when:%d/%m}"
    label = "Adiada até" if dose.status == DoseStatus.SNOOZED else "Próxima dose"

    def take(e):
        if not app.guard_write():
            return
        app.c.schedule.mark_taken(med.id, dose.scheduled_at)
        app.toast(f"{med.display_name} registrado", "Desfazer",
                  lambda e: (app.c.schedule.undo(med.id, dose.scheduled_at), app.refresh()))
        app.refresh()

    sub = " · ".join(x for x in [med.dose_text, med.instructions] if x)
    return ft.Container(
        ft.Column([
            ft.Row([
                ft.Container(ft.Row([ft.Icon(ft.Icons.SCHEDULE, size=16, color="#FFFFFF"),
                                     T(f"{label} · {when:%H:%M}", 13, 700, "#FFFFFF")], spacing=6, tight=True),
                             bgcolor=ft.Colors.with_opacity(0.16, "#FFFFFF"), border_radius=999,
                             padding=ft.Padding.symmetric(horizontal=12, vertical=6)),
                T(eta, 15, 700, th.PRIMARY_ON_DARK),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Column([T(med.display_name, 24, 800, "#FFFFFF"), T(sub, 15, 400, th.PRIMARY_ON_DARK)], spacing=4),
            ft.Row([
                ft.Button(content=T("Marcar como tomado", 16, 800, th.PRIMARY_DARK), icon=ft.Icons.CHECK_CIRCLE,
                          icon_color=th.PRIMARY_DARK, bgcolor="#FFFFFF", height=52, expand=True, on_click=take,
                          style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=16), elevation=0)),
                ft.IconButton(ft.Icons.MORE_HORIZ, icon_color="#FFFFFF", tooltip="Mais opções",
                              bgcolor=ft.Colors.with_opacity(0.16, "#FFFFFF"), width=52, height=52,
                              on_click=lambda e: app.dose_actions(dose)),
            ], spacing=10),
        ], spacing=16),
        bgcolor=th.PRIMARY_DARK, border_radius=26, padding=22,
    )


def _quick(icon, label: str, on_click, bg=th.SURFACE, fg=th.PRIMARY) -> ft.Container:
    return ft.Container(
        ft.Column([ft.Container(ft.Icon(icon, color=fg), width=56, height=56, bgcolor=bg, border_radius=18,
                                alignment=ft.Alignment.CENTER, shadow=th.SHADOW if bg == th.SURFACE else None),
                   T(label, 12, 700)], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
        on_click=on_click, expand=True, border_radius=16, ink=True, padding=ft.Padding.symmetric(vertical=4),
    )


def home_view(app):
    c = app.c
    profile = c.settings.profile()
    first_name = (profile.name or "").split(" ")[0]
    doses = c.schedule.today()
    taken = sum(d.status == DoseStatus.TAKEN for d in doses)
    remaining = sum(d.status in (DoseStatus.DUE, DoseStatus.UPCOMING, DoseStatus.SNOOZED) for d in doses)
    ratio = taken / len(doses) if doses else 1.0
    streak = c.schedule.streak()
    low_stock = [s for s in c.meds.stock_overview() if s.low]
    water = c.hydration.today()

    actions: list[ft.Control] = []
    if app.cloud:
        actions.append(ft.IconButton(ft.Icons.NOTIFICATIONS_OUTLINED, icon_color=th.INK, bgcolor=th.SURFACE,
                                     tooltip="Notificações", on_click=lambda e: app.go("notifications"),
                                     badge=ft.Badge(label=str(app.unread), bgcolor=th.DANGER) if app.unread else None))
    actions += [
        ft.IconButton(ft.Icons.SMART_TOY_OUTLINED, icon_color=th.INK, bgcolor=th.SURFACE, tooltip="Assistente",
                      on_click=lambda e: app.go("assistant")),
        ft.Container(avatar(initials(profile.name or "Você")), on_click=lambda e: app.go("profile"),
                     tooltip="Perfil", border_radius=44),
    ]
    header = ft.Container(ft.Row([
        ft.Row([icon_badge(ft.Icons.MEDICATION, th.PRIMARY, "#FFFFFF", size=32, radius=10, icon_size=20),
                T("MedRemind", 18, 800, th.PRIMARY)], spacing=8, tight=True),
        ft.Row(actions, spacing=8, tight=True),
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), padding=ft.Padding.only(left=20, right=20, top=16))

    # Quem acompanha outras pessoas vê de quem são os dados e troca com um toque.
    viewing_other = app.cloud and app.patient.role != "owner"
    switcher = None
    if app.cloud and (app.session.follows_others or viewing_other):
        label = (f"Dados de {app.patient.name} · {app.patient.role_label}" + ("" if app.patient.can_write
                                                                             else " · só leitura")
                 if viewing_other else "Seus dados")
        switcher = ft.Container(ft.Row([
            ft.Icon(ft.Icons.SUPERVISOR_ACCOUNT if viewing_other else ft.Icons.PERSON, size=18,
                    color="#FFFFFF" if viewing_other else th.PRIMARY_DARK),
            T(label, 13, 700, "#FFFFFF" if viewing_other else th.PRIMARY_DARK, expand=True),
            T("Trocar", 13, 800, "#FFFFFF" if viewing_other else th.PRIMARY),
        ], spacing=8), bgcolor=th.PRIMARY_DARK if viewing_other else th.PRIMARY_TINT, border_radius=14,
            padding=ft.Padding.symmetric(horizontal=14, vertical=10), on_click=lambda e: app.go("patients"), ink=True)

    if doses:
        status_line = f"{taken} de {len(doses)} doses tomadas hoje." + (" Excelente!" if taken == len(doses) else "")
    else:
        status_line = "Nenhuma dose agendada para hoje."

    if viewing_other:
        greeting_text = f"{first_name or 'Paciente'} hoje"
    else:
        greeting_text = f"{greeting(c.schedule.clock())}{', ' + first_name if first_name else ''}!"
    children: list[ft.Control] = ([switcher] if switcher else []) + [
        ft.Column([T(greeting_text, 28, 800),
                   T(status_line, 15, 400, th.INK_2)], spacing=4),
        ft.Row([
            card(ft.Column([_ring(ratio), T("Meta diária", 13, 600, th.INK_2)], spacing=10,
                           horizontal_alignment=ft.CrossAxisAlignment.CENTER), expand=True, height=200,
                 alignment=ft.Alignment.CENTER),
            ft.Column([
                ft.Container(ft.Column([ft.Row([ft.Icon(ft.Icons.MEDICATION, color="#FFFFFF", size=22),
                                                T(str(remaining), 26, 800, "#FFFFFF")], spacing=8),
                                        T("doses restantes", 13, 600, th.PRIMARY_ON_DARK)], spacing=2,
                                       alignment=ft.MainAxisAlignment.CENTER),
                             bgcolor=th.PRIMARY, border_radius=22, padding=16, expand=True),
                card(ft.Column([ft.Row([ft.Icon(ft.Icons.LOCAL_FIRE_DEPARTMENT, color=th.STREAK, size=22),
                                        T(str(streak), 26, 800)], spacing=8),
                                T("dia seguido" if streak == 1 else "dias seguidos", 13, 600, th.INK_2)], spacing=2,
                               alignment=ft.MainAxisAlignment.CENTER),
                     padding=16, expand=True),
            ], spacing=12, expand=True, height=200, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        ], spacing=12),
        _next_dose_card(app, c.schedule.next_dose()),
    ]

    if low_stock:
        s = low_stock[0]
        msg = "acabou" if s.empty else f"acaba em ~{int(s.days_left)} dias" if s.days_left is not None else "está baixo"
        children.append(card(ft.Row([
            icon_badge(ft.Icons.WARNING_AMBER, th.WARN_TINT, th.WARN_INK),
            ft.Column([T(f"{s.medication.display_name} {msg}", 15, 700),
                       T("Toque para ver o estoque e pedir reposição.", 13, 400, th.INK_2)], spacing=2, expand=True),
            ft.Icon(ft.Icons.CHEVRON_RIGHT, color=th.INK_2),
        ], spacing=12), on_click=lambda e: app.go("stock"), border=ft.Border.all(2, "#E8A54B")))

    children += [
        ft.Row([
            _quick(ft.Icons.ADD, "Adicionar", lambda e: app.go("med_form")),
            _quick(ft.Icons.WATER_DROP, f"Água {water.ratio:.0%}", lambda e: app.go("hydration")),
            _quick(ft.Icons.MIC, "Assistente", lambda e: app.go("assistant")),
            _quick(ft.Icons.EMERGENCY, "SOS", lambda e: app.go("emergency"), th.DANGER_TINT, th.DANGER),
        ], spacing=8),
        section("Programação de hoje", "Histórico", lambda e: app.go("history")),
    ]

    if not doses:
        children.append(card(ft.Column([
            T("Cadastre seu primeiro remédio para receber lembretes.", 15, 600),
            ft.Row([ft.Button(content=T("Adicionar medicação", 15, 800, "#FFFFFF"), icon=ft.Icons.ADD,
                              bgcolor=th.PRIMARY, icon_color="#FFFFFF", on_click=lambda e: app.go("med_form"))]),
        ], spacing=12)))
    for d in doses:
        title_style = {"style": ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH)} \
            if d.status == DoseStatus.TAKEN else None
        sub = f"{d.scheduled_at:%H:%M}"
        if d.status == DoseStatus.TAKEN and d.acted_at:
            sub = f"Tomado às {d.acted_at:%H:%M}"
        elif d.status == DoseStatus.SNOOZED and d.snoozed_until:
            sub = f"Adiado para {d.snoozed_until:%H:%M}"
        elif d.medication.instructions:
            sub += f" · {d.medication.instructions}"
        highlight = d.status == DoseStatus.DUE
        children.append(card(
            ft.Row([
                status_badge(d.status),
                ft.Column([T(d.medication.display_name, 16, 700,
                             th.INK_2 if d.status == DoseStatus.TAKEN else th.INK, **(title_style or {})),
                           T(sub, 13, 400, th.INK_2)], spacing=2, expand=True),
                status_chip(d.status),
            ], spacing=14),
            padding=ft.Padding.symmetric(horizontal=16, vertical=14), radius=20,
            border=ft.Border.all(2, th.PRIMARY) if highlight else None,
            on_click=lambda e, d=d: app.dose_actions(d),
        ))
    return app.screen(header, children)

"""Histórico de adesão, estoque e hidratação."""
from __future__ import annotations

from datetime import timedelta

import flet as ft

from ...core.models import WEEKDAY_LABELS, DoseStatus
from ...core.services.hydration import PRESETS
from ...core.services.medications import ValidationError
from ...core.services.text import liters
from .. import theme as th
from ..components import (
    T,
    card,
    chip,
    empty_state,
    field,
    grouped,
    icon_badge,
    link_button,
    list_row,
    primary_button,
    progress,
    secondary_button,
    section,
    status_badge,
    top_bar,
)
from ..components import STATUS_STYLE

DAY_STYLE = {
    "done": (ft.Icons.CHECK, th.SUCCESS, "#FFFFFF", "Todas tomadas"),
    "partial": (ft.Icons.REMOVE, th.WARN_TINT, th.WARN_INK, "Parcial"),
    "missed": (ft.Icons.CLOSE, th.DANGER_TINT, th.DANGER, "Doses perdidas"),
    "pending": (ft.Icons.SCHEDULE, th.SURFACE, th.INK_2, "Agendado"),
    "empty": (ft.Icons.REMOVE, th.SURFACE, th.LINE_STRONG, "Sem doses"),
}
WEEKDAYS_FULL = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def _day_label(day, today) -> str:
    if day == today:
        return f"Hoje, {WEEKDAYS_FULL[day.weekday()]}"
    if day == today - timedelta(days=1):
        return f"Ontem, {WEEKDAYS_FULL[day.weekday()]}"
    return f"{WEEKDAYS_FULL[day.weekday()].capitalize()}, {day:%d/%m}"


# ---------------------------------------------------------------------- Histórico
def history_view(app, weeks_back: int = 0):
    c = app.c
    today = c.schedule.clock().date()
    ref = today - timedelta(weeks=weeks_back)
    week = c.schedule.week(ref)

    day_cells = []
    for s in week:
        icon, bg, fg, label = DAY_STYLE[s.state]
        is_today = s.day == today
        day_cells.append(ft.Column([
            T(WEEKDAY_LABELS[s.day.weekday()], 12, 800 if is_today else 700, th.PRIMARY if is_today else th.INK_2),
            ft.Container(ft.Icon(icon, size=18, color=fg), width=36, height=36, border_radius=36, bgcolor=bg,
                         alignment=ft.Alignment.CENTER, tooltip=f"{s.day:%d/%m}: {label} ({s.taken}/{s.planned})",
                         border=ft.Border.all(2, th.PRIMARY) if is_today else
                         ft.Border.all(1, th.LINE_STRONG) if s.state in ("pending", "empty") else None),
        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, expand=True))

    week_label = "Esta semana" if weeks_back == 0 else f"{week[0].day:%d/%m} – {week[-1].day:%d/%m}"
    nav = ft.Row([
        ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip="Semana anterior",
                      on_click=lambda e: app.go("history", replace=True, weeks_back=weeks_back + 1)),
        T(week_label, 15, 700),
        ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip="Próxima semana", disabled=weeks_back == 0,
                      on_click=lambda e: app.go("history", replace=True, weeks_back=max(0, weeks_back - 1))),
    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    month = c.schedule.adherence(today - timedelta(days=29), today)
    prev = c.schedule.adherence(today - timedelta(days=59), today - timedelta(days=30))
    delta = (month.rate - prev.rate) * 100 if prev.due and month.due else None
    weekly = c.schedule.weekly_adherence(4)

    bars = []
    for i, (start, rate) in enumerate(weekly):
        current = i == len(weekly) - 1
        h = 110 * (rate or 0)
        bars.append(ft.Column([
            T("—" if rate is None else f"{rate:.0%}", 12, 800 if current else 700, th.PRIMARY if current else th.INK_2),
            ft.Container(height=max(4, h), bgcolor=th.PRIMARY if current else "#9DBBEE",
                         border_radius=ft.BorderRadius.only(top_left=10, top_right=10, bottom_left=4, bottom_right=4)),
            T("Atual" if current else f"{start:%d/%m}", 12, 600, th.INK_2),
        ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, alignment=ft.MainAxisAlignment.END,
            expand=True, height=160))

    adherence_card = card(ft.Column([
        ft.Row([
            ft.Column([T("Adesão nos últimos 30 dias", 14, 700, th.INK_2),
                       T(f"{month.rate:.0%}" if month.due else "—", 40, 800),
                       T(f"{month.on_time_rate:.0%} no horário (±1 h)", 13, 400, th.INK_2)], spacing=2),
            chip(f"{delta:+.0f} pts vs. mês anterior", th.SUCCESS_TINT if delta >= 0 else th.DANGER_TINT,
                 th.SUCCESS_INK if delta >= 0 else th.DANGER,
                 ft.Icons.TRENDING_UP if delta >= 0 else ft.Icons.TRENDING_DOWN) if delta is not None else ft.Container(),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START),
        ft.Row(bars, spacing=14, vertical_alignment=ft.CrossAxisAlignment.END),
    ], spacing=18), padding=20)

    log_sections: list[ft.Control] = [section("Registro detalhado")]
    for offset in range(0, 7):
        day = ref - timedelta(days=offset) if weeks_back == 0 else week[-1].day - timedelta(days=offset)
        if day > today:
            continue
        doses = [d for d in c.schedule.doses_for_day(day) if d.status != DoseStatus.UPCOMING]
        if not doses:
            continue
        rows = []
        for i, d in enumerate(doses):
            right_text = d.acted_at.strftime("%H:%M") if d.acted_at and d.status == DoseStatus.TAKEN else ""
            fg = STATUS_STYLE[d.status][4]
            trailing = ft.Column([T(d.status.label, 13, 800, fg if d.status != DoseStatus.UPCOMING else th.INK_2),
                                  T(right_text, 12, 400, th.INK_2)], spacing=2,
                                 horizontal_alignment=ft.CrossAxisAlignment.END, tight=True)
            rows.append(list_row(status_badge(d.status, 40), d.medication.display_name,
                                 f"Previsto {d.scheduled_at:%H:%M}", trailing, last=i == len(doses) - 1,
                                 on_click=lambda e, d=d: app.dose_actions(d)))
        log_sections += [T(_day_label(day, today).upper(), 12, 700, th.INK_2,
                           style=ft.TextStyle(letter_spacing=0.8)), grouped(rows)]

    header = top_bar("Histórico", big=True, actions=[
        link_button("Relatório", lambda e: app.go("reports"), icon=ft.Icons.DESCRIPTION_OUTLINED)])
    return app.screen(header, [card(ft.Column([nav, ft.Row(day_cells, spacing=2)], spacing=8), padding=14),
                               adherence_card, *log_sections])


# ------------------------------------------------------------------------ Estoque
def stock_view(app):
    c = app.c
    items = c.meds.stock_overview()
    profile = c.settings.profile()

    def refill(med):
        qty = field("Unidades compradas", str(int(med.stock_total) if med.stock_total else 30),
                    keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)
        err = T("", 13, 700, th.DANGER, visible=False)

        def ok(e):
            try:
                units = float((qty.value or "0").replace(",", "."))
                c.meds.refill(med.id, units)
            except ValidationError as exc:
                err.value, err.visible = str(exc), True
            except ValueError:
                err.value, err.visible = "Informe um número válido.", True
            if err.visible:
                err.update()
                return
            app.close_dialog()
            app.toast(f"Estoque de {med.display_name} atualizado")
            app.refresh()

        app.dialog(f"Repor {med.display_name}", ft.Column([qty, err], tight=True, width=320),
                   [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
                    ft.TextButton(content=T("Salvar", 14, 800, th.PRIMARY), on_click=ok)])

    alerts, others = [s for s in items if s.low], [s for s in items if not s.low]
    children: list[ft.Control] = [T("Acompanhe o que resta e reponha antes de acabar.", 15, 400, th.INK_2)]
    for s in alerts:
        m = s.medication
        when = "Acabou" if s.empty else f"Acaba em {int(s.days_left)} dias" if s.days_left is not None else "Estoque baixo"
        children.append(card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, size=18, color=th.WARN_INK), T(when, 13, 800, th.WARN_INK)], spacing=6),
            ft.Row([icon_badge(ft.Icons.MEDICATION, th.WARN_TINT, th.WARN_INK, size=52, radius=16),
                    ft.Column([T(m.display_name, 18, 800),
                               T(f"{m.dose_text} por dose · {len(m.times)}x ao dia", 14, 400, th.INK_2)],
                              spacing=2, expand=True),
                    ft.Column([T(f"{m.stock_units:g}", 30, 800, th.WARN_INK), T("unidades", 12, 600, th.INK_2)],
                              spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END)], spacing=14),
            ft.Row([primary_button("Registrar reposição", lambda e, m=m: refill(m), ft.Icons.ADD_SHOPPING_CART)]),
        ], spacing=14), border=ft.Border.all(2, "#E8A54B"), radius=24, padding=20))

    if others:
        rows = []
        for i, s in enumerate(others):
            m = s.medication
            days = f"~{int(s.days_left)} dias" if s.days_left is not None else "uso eventual"
            rows.append(ft.Container(ft.Column([
                ft.Row([icon_badge(ft.Icons.MEDICATION, size=40, radius=12),
                        ft.Column([T(m.display_name, 15, 700), T(days, 13, 400, th.INK_2)], spacing=2, expand=True),
                        T(f"{m.stock_units:g} un.", 15, 800),
                        ft.IconButton(ft.Icons.ADD, tooltip=f"Repor {m.name}", icon_color=th.PRIMARY,
                                      on_click=lambda e, m=m: refill(m))], spacing=12),
                progress(s.ratio, th.SUCCESS, 6),
            ], spacing=10), padding=ft.Padding.symmetric(vertical=14),
                border=None if i == len(others) - 1 else ft.Border.only(bottom=ft.BorderSide(1, th.SURFACE_2))))
        children += [section("Em dia"), grouped(rows)]
    if not items:
        children.append(empty_state(ft.Icons.INVENTORY_2, "Nenhuma medicação com controle de estoque."))

    if profile.pharmacy_name:
        children += [section("Sua farmácia"), card(ft.Row([
            icon_badge(ft.Icons.LOCAL_PHARMACY, th.SUCCESS_TINT, th.SUCCESS_INK, size=48),
            ft.Column([T(profile.pharmacy_name, 15, 700), T(profile.pharmacy_address or "Endereço não informado",
                                                              13, 400, th.INK_2)], spacing=2, expand=True),
            ft.IconButton(ft.Icons.DIRECTIONS, icon_color=th.PRIMARY, bgcolor=th.PRIMARY_TINT, tooltip="Como chegar",
                          url="https://www.google.com/maps/search/?api=1&query="
                              + (profile.pharmacy_name + " " + profile.pharmacy_address).replace(" ", "+")),
        ], spacing=14))]
    children.append(ft.TextButton(content=T("Encontrar farmácias próximas", 14, 700, th.PRIMARY),
                                  icon=ft.Icons.MAP_OUTLINED, url="https://www.google.com/maps/search/farm%C3%A1cia/"))
    return app.screen(top_bar("Estoque", on_back=app.back), children)


# --------------------------------------------------------------------- Hidratação
def hydration_view(app):
    c = app.c
    day = c.hydration.today()

    def add(kind):
        c.hydration.add_preset(kind)
        app.refresh()

    def custom(e):
        amount = field("Quantidade (ml)", "300", keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)

        def ok(ev):
            try:
                c.hydration.add(int(amount.value or "0"))
            except ValueError:
                amount.error = "Informe entre 1 e 3000 ml"
                amount.update()
                return
            app.close_dialog()
            app.refresh()
        app.dialog("Outra quantidade", ft.Column([amount], tight=True, width=300),
                   [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
                    ft.TextButton(content=T("Adicionar", 14, 800, th.PRIMARY), on_click=ok)])

    def undo(e):
        if c.hydration.undo_last():
            app.toast("Último registro removido")
        app.refresh()

    tip = ("Meta batida! Ótimo trabalho." if day.ratio >= 1 else
           "Continue assim! A hidratação ajuda na absorção dos seus medicamentos.")
    hero = ft.Container(ft.Stack([
        ft.Container(bgcolor="#C6DAF8", height=260 * max(0.06, day.ratio), bottom=0, left=0, right=0,
                     border_radius=ft.BorderRadius.only(top_left=40, top_right=40), animate=400),
        ft.Container(ft.Column([
            ft.Row([ft.Column([T("Hoje", 14, 700, th.INK_2),
                               ft.Row([T(liters(day.total_ml), 48, 800), T(f"de {liters(day.goal_ml)}", 16, 700, th.INK_2)],
                                      spacing=8, vertical_alignment=ft.CrossAxisAlignment.END)], spacing=0),
                    chip(f"{day.ratio:.0%}", th.PRIMARY, "#FFFFFF")],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Container(expand=True),
            ft.Row([ft.Icon(ft.Icons.WATER_DROP, size=20, color="#0A2E66"), T(tip, 14, 600, "#0A2E66", expand=True)],
                   spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
        ]), padding=24, height=260),
    ], height=260), bgcolor=th.SURFACE, border_radius=28, shadow=th.SHADOW, clip_behavior=ft.ClipBehavior.HARD_EDGE)

    def preset_button(kind, icon, label):
        return ft.Container(ft.Column([ft.Icon(icon, color=th.PRIMARY, size=28), T(f"+ {PRESETS[kind]} ml", 16, 800),
                                       T(label, 13, 400, th.INK_2)], spacing=4,
                                      horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
                            expand=True, height=104, bgcolor=th.SURFACE, border_radius=20,
                            border=ft.Border.all(1, th.LINE), alignment=ft.Alignment.CENTER, ink=True,
                            on_click=lambda e: add(kind))

    rows = [list_row(icon_badge(ft.Icons.LOCAL_DRINK if l.kind == "copo" else ft.Icons.WATER, size=40, radius=12),
                     "Copo de água" if l.kind == "copo" else "Garrafa" if l.kind == "garrafa" else "Água",
                     f"{l.logged_at:%H:%M}", T(f"{l.amount_ml} ml", 15, 800), last=i == len(day.logs) - 1)
            for i, l in enumerate(day.logs)]
    children = [
        hero,
        section("Adicionar água"),
        ft.Row([preset_button("copo", ft.Icons.LOCAL_DRINK, "Copo"), preset_button("garrafa", ft.Icons.WATER, "Garrafa")],
               spacing=12),
        ft.Row([secondary_button("Outra quantidade", custom, ft.Icons.EDIT, height=46)]),
        section("Registros de hoje", "Desfazer último" if day.logs else None, undo),
        grouped(rows) if rows else empty_state(ft.Icons.WATER_DROP, "Nenhum registro hoje ainda."),
    ]
    return app.screen(top_bar("Hidratação", on_back=app.back), children)


"""Componentes visuais reutilizáveis."""
from __future__ import annotations

from typing import Callable

import flet as ft

from ..core.models import DoseStatus
from . import theme as th
from .theme import T

Handler = Callable[..., object] | None


def card(content: ft.Control, padding: float = 18, bg: str = th.SURFACE, radius: float = th.R_CARD,
         on_click: Handler = None, border: ft.Border | None = None, shadow: bool = True, **kw) -> ft.Container:
    return ft.Container(
        content=content, padding=padding, bgcolor=bg, border_radius=radius, border=border,
        shadow=th.SHADOW if shadow and bg == th.SURFACE else None, on_click=on_click,
        ink=on_click is not None, **kw,
    )


def icon_badge(icon, bg: str = th.PRIMARY_TINT, fg: str = th.PRIMARY, size: float = 44,
               radius: float = th.R_ICON, icon_size: float = 22) -> ft.Container:
    return ft.Container(ft.Icon(icon, color=fg, size=icon_size), width=size, height=size,
                        bgcolor=bg, border_radius=radius, alignment=ft.Alignment.CENTER)


def chip(label: str, bg: str, fg: str, icon=None) -> ft.Container:
    row = [T(label, 12, 800, fg)]
    if icon:
        row.insert(0, ft.Icon(icon, size=14, color=fg))
    return ft.Container(ft.Row(row, spacing=4, tight=True), bgcolor=bg, border_radius=999,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=6))


def primary_button(text: str, on_click: Handler = None, icon=None, bg: str = th.PRIMARY,
                   fg: str = "#FFFFFF", expand: bool | int | None = True, height: float = 54,
                   disabled: bool = False, url: str | None = None) -> ft.Button:
    return ft.Button(
        content=T(text, 16, 800, fg), icon=icon, icon_color=fg, bgcolor=bg, color=fg,
        on_click=on_click, expand=expand, height=height, disabled=disabled, url=url,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=th.R_BUTTON), elevation=0),
    )


def secondary_button(text: str, on_click: Handler = None, icon=None, fg: str = th.INK,
                     expand: bool | int | None = True, height: float = 54, url: str | None = None,
                     border_color: str = th.LINE_STRONG) -> ft.OutlinedButton:
    return ft.OutlinedButton(
        content=T(text, 15, 700, fg), icon=icon, icon_color=fg, on_click=on_click,
        expand=expand, height=height, url=url,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=th.R_BUTTON),
                             side=ft.BorderSide(1, border_color), bgcolor=th.SURFACE),
    )


def link_button(text: str, on_click: Handler = None, color: str = th.PRIMARY, icon=None) -> ft.TextButton:
    return ft.TextButton(content=T(text, 14, 700, color), icon=icon, icon_color=color, on_click=on_click,
                         style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12)))


def section(title: str, action: str | None = None, on_action: Handler = None, caps: bool = False) -> ft.Row:
    label = T(title.upper(), 12, 700, th.INK_2, style=ft.TextStyle(letter_spacing=0.8)) if caps \
        else T(title, 18, 800)
    row: list[ft.Control] = [label]
    if action:
        row.append(link_button(action, on_action))
    return ft.Row(row, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def top_bar(title: str, on_back: Handler = None, actions: list[ft.Control] | None = None,
            big: bool = False, subtitle: str | None = None) -> ft.Container:
    left: list[ft.Control] = []
    if on_back:
        left.append(ft.IconButton(ft.Icons.ARROW_BACK, icon_color=th.INK, on_click=on_back, tooltip="Voltar"))
    title_col: list[ft.Control] = [T(title, 28 if big else 17, 800 if big else 700)]
    if subtitle:
        title_col.append(T(subtitle, 14, 400, th.INK_2))
    left.append(ft.Column(title_col, spacing=2, tight=True))
    return ft.Container(
        ft.Row([ft.Row(left, spacing=4, tight=True), ft.Row(actions or [], spacing=8, tight=True)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding.only(left=8 if on_back else th.GUTTER, right=12, top=16, bottom=4),
    )


def progress(ratio: float, color: str = th.SUCCESS, height: float = 8, bg: str = th.SURFACE_2) -> ft.ProgressBar:
    return ft.ProgressBar(value=max(0.0, min(1.0, ratio)), color=color, bgcolor=bg, bar_height=height,
                          border_radius=999)


def switch_row(icon, label: str, sub: str, value: bool, on_change: Handler, last: bool = False) -> ft.Container:
    return ft.Container(
        ft.Row([
            icon_badge(icon, size=40, radius=12),
            ft.Column([T(label, 15, 700), T(sub, 13, 400, th.INK_2)], spacing=2, expand=True, tight=True),
            ft.Switch(value=value, on_change=on_change, active_color="#FFFFFF", active_track_color=th.PRIMARY),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(vertical=12),
        border=None if last else ft.Border.only(bottom=ft.BorderSide(1, th.SURFACE_2)),
    )


def list_row(leading: ft.Control, title: str, subtitle: str = "", trailing: ft.Control | None = None,
             last: bool = False, on_click: Handler = None, title_style: dict | None = None) -> ft.Container:
    col = [T(title, 15, 700, **(title_style or {}))]
    if subtitle:
        col.append(T(subtitle, 13, 400, th.INK_2))
    row: list[ft.Control] = [leading, ft.Column(col, spacing=2, expand=True, tight=True)]
    if trailing:
        row.append(trailing)
    return ft.Container(
        ft.Row(row, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(vertical=12), on_click=on_click,
        border=None if last else ft.Border.only(bottom=ft.BorderSide(1, th.SURFACE_2)),
    )


def grouped(rows: list[ft.Control]) -> ft.Container:
    return card(ft.Column(rows, spacing=0), padding=ft.Padding.symmetric(horizontal=16, vertical=2), radius=20)


def avatar(initials: str, size: float = 44, bg: str = th.AVATAR_BG, fg: str = th.AVATAR_INK) -> ft.Container:
    return ft.Container(T(initials, size * 0.34, 800, fg), width=size, height=size, bgcolor=bg,
                        border_radius=size, alignment=ft.Alignment.CENTER)


def initials(name: str) -> str:
    parts = [p for p in name.replace("Dra.", "").replace("Dr.", "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def empty_state(icon, text: str) -> ft.Container:
    return ft.Container(ft.Column([ft.Icon(icon, size=36, color=th.INK_2), T(text, 14, 500, th.INK_2,
                                   text_align=ft.TextAlign.CENTER)],
                                  horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                        padding=32, alignment=ft.Alignment.CENTER)


def field(label: str, value: str = "", hint: str = "", **kw) -> ft.TextField:
    return ft.TextField(label=label, value=value, hint_text=hint, border_radius=14, border_color=th.LINE_STRONG,
                        focused_border_color=th.PRIMARY, bgcolor=th.SURFACE, text_size=16,
                        label_style=ft.TextStyle(font_family="Jakarta600", color=th.INK_2), **kw)


def pill_toggle(options: list[tuple[str, str]], selected: str, on_select: Callable[[str], None],
                icons: dict | None = None) -> ft.Row:
    """Grupo de botões exclusivos (substitui SegmentedButton com visual próprio)."""
    def make(value: str, label: str) -> ft.Container:
        on = value == selected
        content: list[ft.Control] = []
        if icons and value in icons:
            content.append(ft.Icon(icons[value], size=20, color=th.PRIMARY_DARK if on else th.INK))
        content.append(T(label, 12 if icons else 13, 700, th.PRIMARY_DARK if on else th.INK, max_lines=1,
                         overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER))
        return ft.Container(
            ft.Column(content, spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)
            if icons else ft.Row(content, alignment=ft.MainAxisAlignment.CENTER),
            expand=None if icons else True, width=94 if icons else None, height=72 if icons else 44, border_radius=12, padding=ft.Padding.symmetric(horizontal=2), alignment=ft.Alignment.CENTER,
            bgcolor=th.PRIMARY_TINT if on else th.SURFACE,
            border=ft.Border.all(2 if on else 1, th.PRIMARY if on else th.LINE),
            on_click=lambda e, v=value: on_select(v), ink=True,
        )
    return ft.Row([make(v, l) for v, l in options], spacing=8, wrap=bool(icons), run_spacing=8)


# Estilo por status de dose ---------------------------------------------------------
STATUS_STYLE = {
    DoseStatus.TAKEN: (ft.Icons.CHECK, th.SUCCESS, "#FFFFFF", th.SUCCESS_TINT, th.SUCCESS_INK),
    DoseStatus.DUE: (ft.Icons.NOTIFICATIONS_ACTIVE, th.PRIMARY_TINT, th.PRIMARY, th.PRIMARY, "#FFFFFF"),
    DoseStatus.SNOOZED: (ft.Icons.SNOOZE, th.WARN_TINT, th.WARN_INK, th.WARN_TINT, th.WARN_INK),
    DoseStatus.UPCOMING: (ft.Icons.SCHEDULE, th.SURFACE_2, th.INK_2, th.SURFACE_2, th.INK_2),
    DoseStatus.MISSED: (ft.Icons.CLOSE, th.DANGER_TINT, th.DANGER, th.DANGER_TINT, th.DANGER),
    DoseStatus.SKIPPED: (ft.Icons.REDO, th.SURFACE_2, th.INK_2, th.SURFACE_2, th.INK_2),
}


def status_chip(status: DoseStatus) -> ft.Container:
    _, _, _, bg, fg = STATUS_STYLE[status]
    return chip(status.label, bg, fg)


def status_badge(status: DoseStatus, size: float = 44) -> ft.Container:
    icon, bg, fg, _, _ = STATUS_STYLE[status]
    return icon_badge(icon, bg, fg, size=size)

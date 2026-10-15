"""Assistente (agente com ferramentas) e modo de emergência."""
from __future__ import annotations

import flet as ft

from .. import theme as th
from ..components import T, avatar, card, grouped, initials, list_row, primary_button, section, top_bar

SUGGESTIONS = ["Quais são meus remédios hoje?", "Qual a próxima dose?", "Bebi um copo de água",
               "Como está meu estoque?", "Como estou na adesão?"]


def _bubble(text: str, mine: bool) -> ft.Row:
    return ft.Row([ft.Container(
        T(text, 15, 500, "#FFFFFF" if mine else th.INK, selectable=True),
        bgcolor=th.PRIMARY if mine else th.SURFACE, padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        border_radius=ft.BorderRadius.only(top_left=18, top_right=18, bottom_left=18 if mine else 4,
                                           bottom_right=4 if mine else 18),
        shadow=None if mine else th.SHADOW, width=None,
    )], alignment=ft.MainAxisAlignment.END if mine else ft.MainAxisAlignment.START, wrap=True)


def assistant_view(app):
    c = app.c
    history: list[tuple[str, bool]] = app.__dict__.setdefault("chat", [
        ("Olá! Sou o assistente do MedRemind. Posso consultar e registrar suas doses, água e estoque.", False)])
    messages = ft.ListView([_bubble(t, m) for t, m in history], spacing=10, expand=True, auto_scroll=True,
                           padding=ft.Padding.symmetric(horizontal=th.GUTTER, vertical=12))
    thinking = ft.ProgressBar(color=th.PRIMARY, bgcolor=th.PRIMARY_TINT, visible=False, bar_height=3)
    box = ft.TextField(hint_text="Pergunte ou diga “tomei a aspirina”", border_radius=24, expand=True,
                       border_color=th.LINE_STRONG, focused_border_color=th.PRIMARY, bgcolor=th.SURFACE,
                       text_size=15, shift_enter=True, content_padding=ft.Padding.symmetric(horizontal=18, vertical=12))

    def send(text: str):
        text = (text or "").strip()
        if not text:
            return
        history.append((text, True))
        messages.controls.append(_bubble(text, True))
        box.value = ""
        thinking.visible = True
        app.page.update()
        reply = c.assistant.reply(text)
        history.append((reply.text, False))
        messages.controls.append(_bubble(reply.text, False))
        if reply.tools_used:
            messages.controls.append(ft.Row([T("Ações: " + ", ".join(t.replace("_", " ") for t in reply.tools_used),
                                               11, 600, th.INK_2)]))
        thinking.visible = False
        app.page.update()

    box.on_submit = lambda e: send(box.value)
    chips = ft.Row([ft.Container(T(s, 13, 700, th.PRIMARY_DARK), bgcolor=th.PRIMARY_TINT, border_radius=999,
                                 padding=ft.Padding.symmetric(horizontal=12, vertical=8), ink=True,
                                 on_click=lambda e, s=s: send(s)) for s in SUGGESTIONS],
                   scroll=ft.ScrollMode.AUTO, spacing=8)
    header = top_bar("Assistente", on_back=app.back, subtitle=f"Motor: {c.assistant.engine}")
    composer = ft.Container(ft.Column([
        chips,
        ft.Row([box, ft.IconButton(ft.Icons.SEND, icon_color="#FFFFFF", bgcolor=th.PRIMARY, tooltip="Enviar",
                                   width=48, height=48, on_click=lambda e: send(box.value))], spacing=8),
    ], spacing=10), padding=ft.Padding.only(left=th.GUTTER, right=th.GUTTER, top=10, bottom=16),
        bgcolor=th.SURFACE, border=ft.Border.only(top=ft.BorderSide(1, th.LINE)))
    return ft.Column([header, thinking, messages, composer], spacing=0, expand=True)


def emergency_view(app):
    c = app.c
    p = c.settings.profile()
    contacts = c.contacts.list()
    meds = [m for m in c.meds.list() if not m.paused]
    rows = [list_row(avatar(initials(x.name), 40, th.PRIMARY_TINT, th.PRIMARY_DARK), x.name, x.relation,
                     ft.IconButton(ft.Icons.CALL, icon_color="#FFFFFF", bgcolor=th.SUCCESS, url=f"tel:{x.phone}",
                                   tooltip=f"Ligar para {x.name}", disabled=not x.phone), last=i == len(contacts) - 1)
            for i, x in enumerate(contacts)]

    def info(label, value):
        return ft.Column([T(label.upper(), 11, 700, th.INK_2, style=ft.TextStyle(letter_spacing=0.8)),
                          T(value or "Não informado", 15, 700)], spacing=2)

    children = [
        ft.Container(ft.Column([
            ft.Icon(ft.Icons.EMERGENCY, color="#FFFFFF", size=40),
            T("Precisa de ajuda agora?", 22, 800, "#FFFFFF"),
            T("Em emergência médica, ligue para o SAMU.", 15, 500, "#FDE8E6"),
            ft.Row([primary_button("Ligar 192 (SAMU)", None, ft.Icons.CALL, bg="#FFFFFF", fg=th.DANGER, url="tel:192")]),
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER), bgcolor=th.DANGER, border_radius=26, padding=24),
        section("Contatos de emergência"),
        grouped(rows) if rows else card(T("Cadastre contatos no Perfil.", 14, 500, th.INK_2)),
        section("Ficha médica"),
        card(ft.Column([
            ft.Row([info("Nome", p.name), info("Tipo sanguíneo", p.blood_type)], spacing=24),
            info("Alergias", p.allergies),
            info("Condições", p.conditions),
            info("Medicações em uso", ", ".join(m.display_name for m in meds) or "Nenhuma"),
        ], spacing=14)),
        T("Mostre esta tela à equipe de atendimento.", 13, 500, th.INK_2, text_align=ft.TextAlign.CENTER),
    ]
    return app.screen(top_bar("Modo de emergência", on_back=app.back), children)


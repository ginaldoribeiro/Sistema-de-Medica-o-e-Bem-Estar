"""Conta na nuvem: entrar/criar conta, equipe de cuidado, pacientes acompanhados e notificações."""
from __future__ import annotations

from datetime import datetime

import flet as ft

from ...client.api import ApiError
from .. import theme as th
from ..components import (
    T,
    avatar,
    card,
    chip,
    empty_state,
    field,
    grouped,
    icon_badge,
    initials,
    link_button,
    list_row,
    pill_toggle,
    primary_button,
    secondary_button,
    section,
    top_bar,
)

ACCOUNT_TYPES = [("patient", "Paciente"), ("caregiver", "Cuidador"), ("doctor", "Profissional")]
RISK_STYLE = {"alto": (th.DANGER_TINT, th.DANGER, "Risco alto"), "medio": (th.WARN_TINT, th.WARN_INK, "Atenção"),
              "baixo": (th.SUCCESS_TINT, th.SUCCESS_INK, "Em dia")}


def _after_login(app, first_run: bool) -> None:
    app.device.settings.set("mode", "cloud")
    app.request_sync()
    if first_run and not app.device.security.has_pin:
        app.go("pin_setup", replace=True, first_run=True)
    else:
        app.unlock()


# -------------------------------------------------------------- entrar / criar
def account_view(app, first_run: bool = False, mode: str = "login", kind: str = "patient"):
    s = app.session
    email = field("E-mail", s.user.get("email", "") if s else "", keyboard_type=ft.KeyboardType.EMAIL,
                  autofocus=True)
    password = field("Senha", password=True, can_reveal_password=True,
                     hint="Mínimo de 8 caracteres, com letras e números" if mode == "register" else "")
    name = field("Seu nome completo")
    crm = field("Registro profissional (CRM, COREN...)", hint="Opcional")
    server = field("Servidor", s.server_url if s else "", hint="https://api.seudominio.com.br")
    error = T("", 13, 700, th.DANGER, visible=False)
    busy = ft.ProgressBar(color=th.PRIMARY, bgcolor=th.PRIMARY_TINT, visible=False, bar_height=3)

    def fail(msg: str):
        error.value, error.visible, busy.visible = msg, True, False
        app.page.update()

    def submit(e):
        busy.visible, error.visible = True, False
        app.page.update()
        if server.value and server.value.strip() != s.server_url:
            s.set_server(server.value.strip())
        try:
            if mode == "register":
                if len((name.value or "").strip()) < 2:
                    return fail("Informe seu nome.")
                s.register(email.value or "", password.value or "", name.value or "", kind, crm.value or "")
            else:
                s.login(email.value or "", password.value or "")
        except ApiError as exc:
            return fail(exc.message if exc.status else "Não foi possível falar com o servidor. Confira o endereço "
                                                         "e a conexão.")
        busy.visible = False
        app.toast(f"Olá, {s.user.get('name', '').split(' ')[0]}!")
        _after_login(app, first_run)

    def offline(e):
        app.device.settings.set("mode", "local")
        if first_run and not app.device.security.has_pin:
            app.go("pin_setup", replace=True, first_run=True)
        else:
            app.unlock()

    fields: list[ft.Control] = []
    if mode == "register":
        fields += [T("Como você vai usar o MedRemind?", 14, 700),
                   pill_toggle(ACCOUNT_TYPES, kind, lambda v: app.go("account", replace=True, first_run=first_run,
                                                                     mode="register", kind=v)),
                   name]
        if kind == "doctor":
            fields.append(crm)
    fields += [email, password]

    advanced = ft.ExpansionTile(title=T("Configuração avançada", 14, 700, th.INK_2), controls=[server],
                                tile_padding=ft.Padding.symmetric(horizontal=0), shape=ft.RoundedRectangleBorder(),
                                collapsed_shape=ft.RoundedRectangleBorder())
    toggle = ("Já tenho conta", "login") if mode == "register" else ("Criar conta", "register")
    children = [
        ft.Container(height=8),
        ft.Row([icon_badge(ft.Icons.MEDICATION, th.PRIMARY, "#FFFFFF", size=32, radius=10, icon_size=20),
                T("MedRemind", 18, 800, th.PRIMARY)], spacing=8),
        T("Criar sua conta" if mode == "register" else "Entrar na sua conta", 26, 800),
        T("Com conta, seus dados ficam em todos os seus aparelhos e você pode compartilhar com cuidadores e "
          "médicos — sempre com a sua permissão.", 15, 400, th.INK_2),
        card(ft.Column(fields + [error, busy], spacing=14)),
        T("Ao criar a conta você aceita os termos de uso e o tratamento dos seus dados de saúde (LGPD)."
          if mode == "register" else "", 12, 500, th.INK_2),
        ft.Row([primary_button("Criar conta" if mode == "register" else "Entrar", submit,
                               ft.Icons.PERSON_ADD if mode == "register" else ft.Icons.LOGIN)]),
        ft.Row([secondary_button(toggle[0], lambda e: app.go("account", replace=True, first_run=first_run,
                                                             mode=toggle[1]), height=48)]),
        advanced,
    ]
    if first_run:
        children.append(ft.Row([link_button("Usar sem conta (só neste aparelho)", offline, th.INK_2)],
                               alignment=ft.MainAxisAlignment.CENTER))
    header = None if first_run else top_bar("Conta", on_back=app.back)
    return app.screen(header, children)


# ------------------------------------------------------------- equipe de cuidado
def care_view(app):
    s = app.session
    pid = s.active.id
    try:
        team = s.api.care_team(pid)
    except ApiError as exc:
        return app.screen(top_bar("Equipe de cuidado", on_back=app.back),
                          [empty_state(ft.Icons.CLOUD_OFF, exc.message or "Sem conexão.")])
    can_manage = team["can_manage"]

    def invite(role: str):
        can_edit = ft.Switch(value=role == "caregiver", active_track_color=th.PRIMARY, active_color="#FFFFFF")

        def create(e):
            try:
                inv = s.api.create_invite(pid, role, bool(can_edit.value))
            except ApiError as exc:
                app.toast(exc.message)
                return
            app.close_dialog()
            code = inv["code"]
            app.dialog("Convite criado", ft.Column([
                T("Peça para a pessoa criar uma conta no MedRemind e informar este código em "
                  "Perfil › Tenho um código:", 14, 400, th.INK_2),
                ft.Container(T(f"{code[:4]}-{code[4:]}", 34, 800, th.PRIMARY_DARK, selectable=True,
                               text_align=ft.TextAlign.CENTER, style=ft.TextStyle(letter_spacing=4)),
                             bgcolor=th.PRIMARY_TINT, border_radius=16, padding=16, alignment=ft.Alignment.CENTER),
                T(f"Válido até {datetime.fromisoformat(str(inv['expires_at'])):%d/%m às %H:%M}. Uso único.", 13, 600,
                  th.INK_2),
            ], spacing=12, tight=True, width=320), [ft.TextButton(content=T("Pronto", 14, 800, th.PRIMARY),
                                                                  on_click=lambda e: (app.close_dialog(), app.refresh()))])

        label = "cuidador(a)" if role == "caregiver" else "médico(a) ou profissional"
        app.dialog(f"Convidar {label}", ft.Column([
            T("Quem aceitar o convite passa a ver seus remédios, doses, estoque e relatórios. "
              "Você pode remover o acesso a qualquer momento.", 14, 400, th.INK_2),
            ft.Row([ft.Column([T("Pode registrar e editar", 15, 700),
                               T("Ex.: marcar doses, repor estoque", 13, 400, th.INK_2)], spacing=2, expand=True),
                    can_edit]),
        ], spacing=14, tight=True, width=340),
            [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
             ft.TextButton(content=T("Gerar código", 14, 800, th.PRIMARY), on_click=create)])

    def remove(m):
        def run():
            try:
                s.api.remove_member(pid, m["id"])
            except ApiError as exc:
                app.toast(exc.message)
                return
            app.toast(f"Acesso de {m['name']} removido")
            app.refresh()
        app.confirm("Remover acesso?", f"{m['name']} deixará de ver seus dados imediatamente.", run,
                    yes="Remover", danger=True)

    def toggle_edit(m):
        def handler(e):
            try:
                s.api.update_member(pid, m["id"], can_edit=e.control.value)
            except ApiError as exc:
                app.toast(exc.message)
        return handler

    rows = []
    for i, m in enumerate(team["members"]):
        trailing = ft.Row([
            ft.Switch(value=m["can_edit"], on_change=toggle_edit(m), active_track_color=th.PRIMARY,
                      active_color="#FFFFFF", tooltip="Pode editar", disabled=not can_manage),
            ft.IconButton(ft.Icons.PERSON_REMOVE, icon_color=th.DANGER, tooltip="Remover acesso",
                          on_click=lambda e, m=m: remove(m), visible=can_manage),
        ], spacing=0, tight=True)
        sub = m["role_label"] + (" · pode editar" if m["can_edit"] else " · só leitura")
        if m.get("professional_id"):
            sub += f" · {m['professional_id']}"
        rows.append(list_row(avatar(initials(m["name"]), 40, th.PRIMARY_TINT, th.PRIMARY_DARK), m["name"], sub,
                             trailing, last=i == len(team["members"]) - 1))

    pending = [list_row(icon_badge(ft.Icons.KEY, th.WARN_TINT, th.WARN_INK, size=40, radius=12),
                        f"{inv['code'][:4]}-{inv['code'][4:]}",
                        ("Cuidador(a)" if inv["role"] == "caregiver" else "Médico(a)") + " · aguardando",
                        link_button("Cancelar", lambda e, c=inv["code"]: (s.api.revoke_invite(pid, c), app.refresh()),
                                    th.DANGER), last=i == len(team["pending_invites"]) - 1)
               for i, inv in enumerate(team["pending_invites"])]

    children: list[ft.Control] = [
        T("Pessoas que acompanham o tratamento de " + ("você" if can_manage else team["owner"]["name"]) + ".",
          15, 400, th.INK_2),
        grouped(rows) if rows else empty_state(ft.Icons.GROUPS, "Ninguém na equipe ainda."),
    ]
    if can_manage:
        children += [
            ft.Row([primary_button("Convidar cuidador", lambda e: invite("caregiver"), ft.Icons.PERSON_ADD, height=48),
                    secondary_button("Convidar médico", lambda e: invite("doctor"), ft.Icons.MEDICAL_SERVICES,
                                     height=48)], spacing=10),
        ]
        if pending:
            children += [section("Convites pendentes"), grouped(pending)]
        children.append(card(ft.Row([icon_badge(ft.Icons.NOTIFICATIONS_ACTIVE, size=40, radius=12),
                                     T("Cuidadores recebem um aviso quando uma dose passa do horário sem registro, e "
                                       "quando um remédio está acabando.", 13, 500, th.INK_2, expand=True)],
                                    spacing=12), bg=th.PRIMARY_TINT, shadow=False))
    return app.screen(top_bar("Equipe de cuidado", on_back=app.back), children)


def accept_code_dialog(app):
    s = app.session
    code = field("Código do convite", hint="Ex.: K7QM-4T2X", autofocus=True,
                 capitalization=ft.TextCapitalization.CHARACTERS)

    def ok(e):
        try:
            res = s.api.accept_invite((code.value or "").replace("-", "").strip())
        except ApiError as exc:
            code.error = exc.message
            code.update()
            return
        s.refresh_patients()
        app.close_dialog()
        app.toast(f"Agora você acompanha {res['patient_name']}")
        app.switch_patient(res["patient_id"])

    app.dialog("Tenho um código", ft.Column([T("Digite o código que o paciente gerou em Equipe de cuidado.", 14, 400,
                                                 th.INK_2), code], spacing=12, tight=True, width=320),
               [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
                ft.TextButton(content=T("Entrar na equipe", 14, 800, th.PRIMARY), on_click=ok)])


# ------------------------------------------------------- pacientes acompanhados
def _badge(metrics: dict | None, active: bool) -> ft.Control:
    if metrics:
        bg, fg, label = RISK_STYLE[metrics["risk"]]
        return chip(label, bg, fg)
    return chip("Em foco", th.PRIMARY, "#FFFFFF") if active else ft.Container()


def patients_view(app):
    s = app.session
    s.refresh_patients()
    try:
        metrics = {r["patient_id"]: r for r in s.api.dashboard()}
        offline = False
    except ApiError:
        metrics, offline = {}, True

    cards: list[ft.Control] = []
    for p in sorted(s.patients, key=lambda p: (p.role != "owner",
                                               {"alto": 0, "medio": 1, "baixo": 2}.get(
                                                   metrics.get(p.id, {}).get("risk"), 3), p.name)):
        m = metrics.get(p.id)
        active = s.active and s.active.id == p.id
        rows: list[ft.Control] = [ft.Row([
            avatar(initials(p.name), 48, th.PRIMARY_TINT if p.role != "owner" else th.AVATAR_BG,
                   th.PRIMARY_DARK if p.role != "owner" else th.AVATAR_INK),
            ft.Column([T(p.name if p.role != "owner" else f"{p.name} (você)", 16, 800),
                       T(p.role_label + ("" if p.can_write else " · só leitura"), 13, 500, th.INK_2)],
                      spacing=2, expand=True),
            _badge(m, active),
        ], spacing=12)]
        if m:
            adh = "—" if m["adherence_7d"] is None else f"{m['adherence_7d']:.0%}"
            rows.append(ft.Row([
                ft.Column([T(adh, 20, 800), T("adesão 7 dias", 12, 600, th.INK_2)], spacing=0, expand=True),
                ft.Column([T(f"{m['taken_today']}/{m['planned_today']}", 20, 800), T("doses hoje", 12, 600, th.INK_2)],
                          spacing=0, expand=True),
                ft.Column([T(str(m["missed_today"]), 20, 800, th.DANGER if m["missed_today"] else th.INK),
                           T("perdidas hoje", 12, 600, th.INK_2)], spacing=0, expand=True),
            ]))
            if m["low_stock"]:
                rows.append(ft.Row([ft.Icon(ft.Icons.WARNING_AMBER, size=16, color=th.WARN_INK),
                                    T("Estoque baixo: " + ", ".join(m["low_stock"]), 13, 600, th.WARN_INK, expand=True)],
                                   spacing=6))
        cards.append(card(ft.Column(rows, spacing=14), on_click=lambda e, p=p: app.switch_patient(p.id),
                          border=ft.Border.all(2, th.PRIMARY) if active else None))

    children: list[ft.Control] = [
        T("Toque em um paciente para ver e acompanhar os dados dele.", 15, 400, th.INK_2),
        *cards,
        ft.Row([secondary_button("Tenho um código de convite", lambda e: accept_code_dialog(app), ft.Icons.KEY,
                                 height=48)]),
    ]
    if offline:
        children.insert(0, card(T("Sem conexão: mostrando a última lista salva.", 13, 600, th.WARN_INK),
                                bg=th.WARN_TINT, shadow=False))
    return app.screen(top_bar("Pacientes", on_back=app.back), children)


# ----------------------------------------------------------------- notificações
NOTIF_ICON = {"dose_perdida": (ft.Icons.ALARM_OFF, th.DANGER_TINT, th.DANGER),
              "estoque_baixo": (ft.Icons.INVENTORY_2, th.WARN_TINT, th.WARN_INK),
              "convite_aceito": (ft.Icons.GROUP_ADD, th.SUCCESS_TINT, th.SUCCESS_INK)}


def notifications_view(app):
    s = app.session
    try:
        data = s.api.notifications()
    except ApiError as exc:
        return app.screen(top_bar("Notificações", on_back=app.back),
                          [empty_state(ft.Icons.CLOUD_OFF, exc.message or "Sem conexão.")])

    def read_all(e):
        s.api.read_all_notifications()
        app.unread = 0
        app.refresh()

    rows = []
    for i, n in enumerate(data["items"]):
        icon, bg, fg = NOTIF_ICON.get(n["kind"], (ft.Icons.NOTIFICATIONS, th.SURFACE_2, th.INK_2))
        when = datetime.fromisoformat(str(n["created_at"]))
        rows.append(list_row(icon_badge(icon, bg, fg, size=40, radius=12), n["title"], n["body"],
                             T(f"{when:%d/%m %H:%M}", 12, 800 if not n["read"] else 500,
                               th.PRIMARY if not n["read"] else th.INK_2),
                             last=i == len(data["items"]) - 1,
                             on_click=(lambda e, pid=n["patient_id"]: app.switch_patient(pid))
                             if n.get("patient_id") and s.active and n["patient_id"] != s.active.id else None))
    header = top_bar("Notificações", on_back=app.back,
                     actions=[link_button("Marcar todas como lidas", read_all)] if data["unread"] else None)
    return app.screen(header, [grouped(rows) if rows else empty_state(ft.Icons.NOTIFICATIONS_NONE,
                                                                     "Nenhuma notificação.")])

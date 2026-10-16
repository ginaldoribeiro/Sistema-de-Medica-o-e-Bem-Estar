"""Perfil, contatos, notificações, segurança, backup, relatórios e auditoria."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import flet as ft

from ...core.models import Contact
from ...core.services.audit import AuditService
from ...core.services.backup import BackupError
from .. import theme as th
from ..components import (
    T,
    avatar,
    card,
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
    switch_row,
    top_bar,
)


def _edit_profile(app):
    if not app.guard_write():
        return
    c = app.c
    p = c.settings.profile()
    name = field("Nome completo", p.name)
    birth = field("Nascimento (DD/MM/AAAA)", p.birth_date.strftime("%d/%m/%Y") if p.birth_date else "")
    email = field("E-mail", p.email, keyboard_type=ft.KeyboardType.EMAIL)
    phone = field("Telefone", p.phone, keyboard_type=ft.KeyboardType.PHONE)
    blood = field("Tipo sanguíneo", p.blood_type, "Ex.: O+")
    allergies = field("Alergias", p.allergies, multiline=True, min_lines=1, max_lines=3)
    conditions = field("Condições de saúde", p.conditions, multiline=True, min_lines=1, max_lines=3)
    pharmacy = field("Farmácia", p.pharmacy_name)
    pharmacy_addr = field("Endereço da farmácia", p.pharmacy_address)
    goal = field("Meta de água (ml/dia)", str(p.water_goal_ml), keyboard_type=ft.KeyboardType.NUMBER)
    err = T("", 13, 700, th.DANGER, visible=False)

    def save(e):
        try:
            p.birth_date = None
            if birth.value and birth.value.strip():
                d, m, y = (int(x) for x in birth.value.strip().split("/"))
                p.birth_date = date(y, m, d)
            p.water_goal_ml = max(500, min(6000, int(goal.value or "2000")))
        except ValueError:
            err.value, err.visible = "Confira a data (DD/MM/AAAA) e a meta de água.", True
            err.update()
            return
        p.name, p.email, p.phone = name.value.strip(), email.value.strip(), phone.value.strip()
        p.blood_type, p.allergies, p.conditions = blood.value.strip(), allergies.value.strip(), conditions.value.strip()
        p.pharmacy_name, p.pharmacy_address = pharmacy.value.strip(), pharmacy_addr.value.strip()
        if not p.health_id:
            import secrets
            p.health_id = f"MR-{secrets.randbelow(90000) + 10000}-{initials(p.name or 'MR')}"
        c.settings.save_profile(p)
        app.close_dialog()
        app.toast("Perfil atualizado")
        app.refresh()

    app.dialog("Editar perfil", ft.Column([name, birth, email, phone, blood, allergies, conditions, pharmacy,
                                           pharmacy_addr, goal, err], spacing=12, tight=True, width=360),
               [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
                ft.TextButton(content=T("Salvar", 14, 800, th.PRIMARY), on_click=save)])


def _add_contact(app):
    if not app.guard_write():
        return
    name = field("Nome")
    relation = field("Relação", hint="Ex.: Filha, Cardiologista")
    phone = field("Telefone", keyboard_type=ft.KeyboardType.PHONE)
    doctor = ft.Checkbox(label="É profissional de saúde", value=False, active_color=th.PRIMARY)

    def save(e):
        if not (name.value or "").strip():
            name.error = "Informe o nome"
            name.update()
            return
        app.c.contacts.add(Contact(name.value, relation.value or "", phone.value or "", bool(doctor.value)))
        app.close_dialog()
        app.refresh()

    app.dialog("Novo contato", ft.Column([name, relation, phone, doctor], spacing=12, tight=True, width=340),
               [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
                ft.TextButton(content=T("Salvar", 14, 800, th.PRIMARY), on_click=save)])


def _account_section(app) -> list[ft.Control]:
    """Conta na nuvem: sincronização, equipe, pacientes, LGPD e saída."""
    if not app.session:
        return []
    if not app.cloud:
        return [card(ft.Row([
            icon_badge(ft.Icons.CLOUD_OFF, th.SURFACE_2, th.INK_2),
            ft.Column([T("Usando só neste aparelho", 15, 700),
                       T("Crie uma conta para sincronizar e compartilhar com cuidadores e médicos.", 13, 400,
                         th.INK_2)], spacing=2, expand=True),
            link_button("Entrar", lambda e: app.go("account")),
        ], spacing=12))]

    s = app.session
    res = app.last_sync
    pending = s.pending()
    if res is None:
        status, color = "Ainda não sincronizado nesta sessão", th.INK_2
    elif res.ok:
        status, color = f"Sincronizado às {res.at:%H:%M}" + (f" · {pending} pendente(s)" if pending else ""), th.SUCCESS_INK
    else:
        status, color = res.error + (f" ({pending} alteração(ões) guardada(s))" if pending else ""), th.WARN_INK

    def export(e):
        import json

        try:
            data = s.api.export()
        except Exception as exc:  # noqa: BLE001 — mensagem amigável para qualquer falha
            app.toast(getattr(exc, "message", str(exc)))
            return
        folder = app.device.data_dir / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"meus-dados-{datetime.now():%Y%m%d-%H%M}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        app.dialog("Dados exportados", T(f"Arquivo salvo em:\n{path}", 14, 500, th.INK_2, selectable=True),
                   [ft.TextButton(content=T("OK", 14, 800, th.PRIMARY), on_click=app.close_dialog)])

    def delete_account(e):
        pwd = field("Confirme sua senha", password=True, autofocus=True)

        def ok(ev):
            try:
                s.delete_account(pwd.value or "")
            except Exception as exc:  # noqa: BLE001
                pwd.error = getattr(exc, "message", "Não foi possível excluir")
                pwd.update()
                return
            app.close_dialog()
            app.device.settings.delete("mode")
            app.toast("Conta e dados excluídos do servidor.")
            app.go("account", reset=True, first_run=True)
        app.dialog("Excluir conta?", ft.Column([
            T("Sua conta, seus remédios, histórico e vínculos com cuidadores serão apagados do servidor. "
              "Isso não pode ser desfeito. Exporte seus dados antes, se quiser guardá-los.", 14, 400, th.INK_2),
            pwd], spacing=12, tight=True, width=340),
            [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
             ft.TextButton(content=T("Excluir definitivamente", 14, 800, th.DANGER), on_click=ok)])

    def logout(e):
        def run():
            s.logout()
            app.device.settings.delete("mode")
            app.go("account", reset=True, first_run=True)
        app.confirm("Sair da conta?", "Os dados em cache neste aparelho serão apagados. Tudo continua salvo no servidor.",
                    run, yes="Sair")

    from .account import accept_code_dialog

    chevron = ft.Icon(ft.Icons.CHEVRON_RIGHT, color=th.INK_2)
    rows = [
        list_row(icon_badge(ft.Icons.GROUPS, size=40, radius=12), "Equipe de cuidado",
                 "Cuidadores e médicos com acesso", chevron, on_click=lambda e: app.go("care")),
        list_row(icon_badge(ft.Icons.SUPERVISOR_ACCOUNT, size=40, radius=12), "Pacientes",
                 f"{len(s.patients)} perfil(is) acessível(is)", chevron, on_click=lambda e: app.go("patients")),
        list_row(icon_badge(ft.Icons.KEY, size=40, radius=12), "Tenho um código de convite",
                 "Para acompanhar outra pessoa", chevron, on_click=lambda e: accept_code_dialog(app)),
        list_row(icon_badge(ft.Icons.NOTIFICATIONS, size=40, radius=12), "Notificações",
                 f"{app.unread} não lida(s)" if app.unread else "Alertas de doses e estoque", chevron,
                 on_click=lambda e: app.go("notifications")),
        list_row(icon_badge(ft.Icons.FILE_DOWNLOAD, size=40, radius=12), "Exportar meus dados",
                 "Cópia completa em JSON (LGPD)", chevron, on_click=export),
        list_row(icon_badge(ft.Icons.LOGOUT, th.SURFACE_2, th.INK_2, size=40, radius=12), "Sair da conta", "",
                 None, on_click=logout),
        list_row(icon_badge(ft.Icons.DELETE_FOREVER, th.DANGER_TINT, th.DANGER, size=40, radius=12),
                 "Excluir conta", "Apaga tudo do servidor", None, on_click=delete_account, last=True),
    ]
    return [
        section("Conta", caps=True),
        card(ft.Column([
            ft.Row([icon_badge(ft.Icons.CLOUD_DONE if (res and res.ok) else ft.Icons.CLOUD_SYNC, size=44),
                    ft.Column([T(s.user.get("email", ""), 15, 700), T(status, 13, 600, color)], spacing=2, expand=True),
                    ft.IconButton(ft.Icons.SYNC, icon_color=th.PRIMARY, bgcolor=th.PRIMARY_TINT,
                                  tooltip="Sincronizar agora", on_click=app.sync_now)], spacing=12),
        ], spacing=8)),
        grouped(rows),
    ]


def profile_view(app):
    c = app.c
    p = c.settings.profile()
    prefs = c.reminders.prefs()

    def info(label, value, last=False):
        return ft.Container(ft.Row([T(label, 14, 400, th.INK_2), T(value or "—", 15, 700, text_align=ft.TextAlign.RIGHT)],
                                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            padding=ft.Padding.symmetric(vertical=14),
                            border=None if last else ft.Border.only(bottom=ft.BorderSide(1, th.SURFACE_2)))

    header_card = ft.Container(ft.Row([
        avatar(initials(p.name or "Você"), 64),
        ft.Column([T(p.name or "Complete seu perfil", 20, 800, "#FFFFFF"),
                   ft.Row([ft.Icon(ft.Icons.BADGE, size=16, color=th.PRIMARY_ON_DARK),
                           T(f"ID {p.health_id}" if p.health_id else "Sem ID de saúde", 13, 700, th.PRIMARY_ON_DARK)],
                          spacing=6)], spacing=4, expand=True),
        ft.IconButton(ft.Icons.EDIT, icon_color="#FFFFFF", bgcolor=ft.Colors.with_opacity(0.14, "#FFFFFF"),
                      tooltip="Editar perfil", on_click=lambda e: _edit_profile(app)),
    ], spacing=16), bgcolor=th.PRIMARY_DARK, border_radius=26, padding=20)

    contacts = c.contacts.list()
    contact_rows = [list_row(avatar(initials(x.name), 40, th.PRIMARY_TINT, th.PRIMARY_DARK), x.name,
                             x.relation or ("Profissional de saúde" if x.is_doctor else ""),
                             ft.IconButton(ft.Icons.CALL, icon_color=th.SUCCESS_INK, bgcolor=th.SUCCESS_TINT,
                                           tooltip=f"Ligar para {x.name}", url=f"tel:{x.phone}" if x.phone else None,
                                           disabled=not x.phone),
                             last=i == len(contacts) - 1,
                             on_click=lambda e, x=x: app.confirm("Remover contato?", x.name,
                                                                 lambda: (c.contacts.delete(x.id), app.refresh()),
                                                                 yes="Remover", danger=True))
                    for i, x in enumerate(contacts)]

    def set_pref(key):
        def handler(e):
            c.reminders.save_prefs(**{key: e.control.value})
        return handler

    def security_row():
        if app.device.security.has_pin:
            def remove(e):
                pin = field("PIN atual", password=True, keyboard_type=ft.KeyboardType.NUMBER, autofocus=True)

                def ok(ev):
                    if app.device.security.remove_pin(pin.value or ""):
                        app.device.settings.delete("pin_length")
                        app.close_dialog()
                        app.toast("PIN removido")
                        app.refresh()
                    else:
                        pin.error = "PIN incorreto"
                        pin.update()
                app.dialog("Remover PIN", ft.Column([pin], tight=True, width=300),
                           [ft.TextButton(content=T("Cancelar", 14, 700, th.INK_2), on_click=app.close_dialog),
                            ft.TextButton(content=T("Remover", 14, 800, th.DANGER), on_click=ok)])
            return list_row(icon_badge(ft.Icons.LOCK, size=40, radius=12), "PIN de acesso", "Ativo — pedido ao abrir o app",
                            link_button("Remover", remove, th.DANGER))
        return list_row(icon_badge(ft.Icons.LOCK_OPEN, th.WARN_TINT, th.WARN_INK, size=40, radius=12), "PIN de acesso",
                        "Desativado", link_button("Ativar", lambda e: app.go("pin_setup")))

    tools = [
        list_row(icon_badge(ft.Icons.DESCRIPTION_OUTLINED, size=40, radius=12), "Relatório para o médico",
                 "CSV e página para imprimir", ft.Icon(ft.Icons.CHEVRON_RIGHT, color=th.INK_2),
                 on_click=lambda e: app.go("reports")),
        list_row(icon_badge(ft.Icons.CLOUD_DONE_OUTLINED, size=40, radius=12), "Backup seguro",
                 "Exportar e restaurar seus dados", ft.Icon(ft.Icons.CHEVRON_RIGHT, color=th.INK_2),
                 on_click=lambda e: app.go("backup")),
        list_row(icon_badge(ft.Icons.MANAGE_SEARCH, size=40, radius=12), "Auditoria de acesso",
                 "Quem acessou e o que mudou", ft.Icon(ft.Icons.CHEVRON_RIGHT, color=th.INK_2),
                 on_click=lambda e: app.go("audit")),
        security_row(),
    ]
    tools[-1].border = None

    children = [
        header_card,
        *_account_section(app),
        section("Dados pessoais", caps=True),
        grouped([info("Nascimento", p.birth_date.strftime("%d/%m/%Y") if p.birth_date else ""),
                 info("E-mail", p.email), info("Telefone", p.phone), info("Tipo sanguíneo", p.blood_type, last=True)]),
        section("Contatos de emergência", "Adicionar", lambda e: _add_contact(app), caps=True),
        grouped(contact_rows) if contact_rows else empty_state(ft.Icons.CONTACT_PHONE, "Nenhum contato cadastrado."),
        section("Farmácia", caps=True),
        card(ft.Row([icon_badge(ft.Icons.LOCAL_PHARMACY, th.SUCCESS_TINT, th.SUCCESS_INK, size=40, radius=12),
                     ft.Column([T(p.pharmacy_name or "Não informada", 15, 700),
                                T(p.pharmacy_address or "Toque no lápis acima para cadastrar", 13, 400, th.INK_2)],
                               spacing=2, expand=True),
                     ft.Icon(ft.Icons.CHEVRON_RIGHT, color=th.INK_2)], spacing=12),
             padding=16, radius=20, on_click=lambda e: app.go("stock")),
        section("Notificações", caps=True),
        grouped([
            switch_row(ft.Icons.NOTIFICATIONS_ACTIVE, "Alertas sonoros", "Som no horário da dose", prefs["sound"],
                       set_pref("sound")),
            switch_row(ft.Icons.VIBRATION, "Vibração", "Vibrar junto com o alerta", prefs["vibration"],
                       set_pref("vibration")),
            switch_row(ft.Icons.WARNING_AMBER, "Alerta persistente", f"Repete a cada {prefs['repeat_minutes']} min até confirmar",
                       prefs["persistent"], set_pref("persistent"), last=True),
        ]),
        section("Segurança e dados", caps=True),
        grouped(tools),
        ft.Row([secondary_button("Bloquear agora", lambda e: app.lock(), ft.Icons.LOCK, height=48)],
               visible=app.device.security.has_pin),
        T(f"Assistente: {c.assistant.engine} · dados em {c.data_dir}", 12, 400, th.INK_2,
          text_align=ft.TextAlign.CENTER),
    ]
    return app.screen(top_bar("Perfil", big=True), children)


# ---------------------------------------------------------------------- Relatórios
def reports_view(app, days: int = 30):
    c = app.c
    end = c.schedule.clock().date()
    start = end - timedelta(days=days - 1)
    a = c.schedule.adherence(start, end)
    result = ft.Column(spacing=8)

    def export(e):
        csv_path, html_path = c.reports.export(c.data_dir / "relatorios", days)
        result.controls = [
            card(ft.Column([ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=th.SUCCESS), T("Relatório gerado", 15, 800)], spacing=8),
                            T(f"Planilha: {csv_path}", 13, 400, th.INK_2, selectable=True),
                            T(f"Página para imprimir/salvar em PDF: {html_path}", 13, 400, th.INK_2, selectable=True)],
                           spacing=6), bg=th.SUCCESS_TINT)]
        result.update()

    children = [
        T("Leve um resumo da sua adesão para a consulta.", 15, 400, th.INK_2),
        pill_toggle([("7", "7 dias"), ("30", "30 dias"), ("90", "90 dias")], str(days),
                    lambda v: app.go("reports", replace=True, days=int(v))),
        card(ft.Row([
            ft.Column([T(f"{a.rate:.0%}" if a.due else "—", 32, 800), T("doses tomadas", 13, 600, th.INK_2)], expand=True),
            ft.Column([T(f"{a.on_time_rate:.0%}" if a.due else "—", 32, 800), T("no horário", 13, 600, th.INK_2)], expand=True),
            ft.Column([T(str(a.due - a.taken), 32, 800), T("não tomadas", 13, 600, th.INK_2)], expand=True),
        ])),
        T(f"Período: {start:%d/%m/%Y} a {end:%d/%m/%Y} · {len(c.meds.list())} medicações", 13, 500, th.INK_2),
        ft.Row([primary_button("Gerar relatório", export, ft.Icons.DESCRIPTION)]),
        result,
    ]
    return app.screen(top_bar("Relatório médico", on_back=app.back), children)


# --------------------------------------------------------------------------- Backup
def backup_view(app):
    c = app.c
    folder = c.data_dir / "backups"
    files = sorted(folder.glob("medremind-backup-*.json"), reverse=True) if folder.exists() else []

    def export(e):
        path = c.backup.export_file(folder)
        app.toast(f"Backup salvo: {path.name}")
        app.refresh()

    def restore(path: Path):
        def run():
            try:
                counts = c.backup.import_file(path)
            except BackupError as exc:
                app.toast(str(exc))
                return
            app.toast(f"Restaurado: {counts.get('medications', 0)} medicações, {counts.get('dose_logs', 0)} registros")
            app.go("home", reset=True)
        app.confirm("Restaurar este backup?", f"{path.name}\nOs dados atuais serão substituídos.", run,
                    yes="Restaurar", danger=True)

    rows = [list_row(icon_badge(ft.Icons.DESCRIPTION_OUTLINED, size=40, radius=12), f.name,
                     f"{f.stat().st_size / 1024:.1f} KB", link_button("Restaurar", lambda e, f=f: restore(f)),
                     last=i == len(files) - 1) for i, f in enumerate(files[:10])]
    children = [
        card(ft.Column([
            ft.Row([icon_badge(ft.Icons.SHIELD, size=48), ft.Column([
                T("Seus dados, sob seu controle", 16, 800),
                T("O backup é um arquivo JSON com verificação de integridade (SHA-256). Seu PIN nunca é incluído.",
                  13, 400, th.INK_2)], spacing=4, expand=True)], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row([primary_button("Exportar backup agora", export, ft.Icons.DOWNLOAD)]),
        ], spacing=16)),
        T(f"Pasta: {folder}", 12, 400, th.INK_2, selectable=True),
        section("Backups salvos"),
        grouped(rows) if rows else empty_state(ft.Icons.CLOUD_OFF, "Nenhum backup ainda."),
        T("Para levar a outro aparelho, copie o arquivo para a pasta de backups do novo aparelho e toque em Restaurar.",
          13, 400, th.INK_2),
    ]
    return app.screen(top_bar("Backup seguro", on_back=app.back), children)


# ------------------------------------------------------------------------ Auditoria
def audit_view(app):
    entries = app.c.audit.recent(80)
    icons = {"login_falhou": (ft.Icons.GPP_BAD, th.DANGER_TINT, th.DANGER),
             "login_ok": (ft.Icons.VERIFIED_USER, th.SUCCESS_TINT, th.SUCCESS_INK),
             "api_acesso": (ft.Icons.API, th.WARN_TINT, th.WARN_INK)}
    rows = []
    for i, a in enumerate(entries):
        icon, bg, fg = icons.get(a.event, (ft.Icons.HISTORY, th.SURFACE_2, th.INK_2))
        rows.append(list_row(icon_badge(icon, bg, fg, size=36, radius=10, icon_size=18), AuditService.label(a.event),
                             a.detail, T(f"{a.created_at:%d/%m %H:%M}", 12, 600, th.INK_2), last=i == len(entries) - 1))
    failed = sum(1 for a in entries if a.event == "login_falhou")
    children = [
        card(ft.Row([icon_badge(ft.Icons.GPP_BAD if failed else ft.Icons.VERIFIED_USER,
                                th.DANGER_TINT if failed else th.SUCCESS_TINT, th.DANGER if failed else th.SUCCESS_INK),
                     T(f"{failed} tentativa(s) de acesso negadas recentemente." if failed
                       else "Nenhuma tentativa de acesso suspeita.", 15, 700, expand=True)], spacing=12)),
        grouped(rows) if rows else empty_state(ft.Icons.HISTORY, "Sem eventos."),
    ]
    return app.screen(top_bar("Auditoria de acesso", on_back=app.back), children)

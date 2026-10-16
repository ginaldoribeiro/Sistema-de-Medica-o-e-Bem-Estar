"""Boas-vindas, consentimento (LGPD), bloqueio por PIN e criação de PIN."""
from __future__ import annotations

import flet as ft

from .. import theme as th
from ..components import T, card, icon_badge, link_button, primary_button

SLIDES = [
    (ft.Icons.MEDICATION, "Bem-vindo ao MedRemind",
     "Seu companheiro de saúde inteligente. Nunca mais esqueça de tomar seus medicamentos."),
    (ft.Icons.INVENTORY_2, "Estoque sob controle",
     "O app conta o que resta de cada remédio e avisa antes de acabar."),
    (ft.Icons.SMART_TOY, "Assistente que entende você",
     "Pergunte “quais são meus remédios hoje?” ou diga “tomei a aspirina”."),
]


def _logo(size: float = 32) -> ft.Row:
    return ft.Row([icon_badge(ft.Icons.MEDICATION, th.PRIMARY, "#FFFFFF", size=size, radius=size * 0.31,
                              icon_size=size * 0.62), T("MedRemind", 18, 800, th.PRIMARY)], spacing=8, tight=True)


def onboarding_view(app, i: int = 0):
    icon, title, text = SLIDES[i]
    last = i == len(SLIDES) - 1

    def finish(e=None):
        app.device.settings.set("onboarded", True)
        app.go("consent", replace=True)

    dots = ft.Row([ft.Container(width=28 if n == i else 8, height=8, border_radius=8,
                                bgcolor=th.PRIMARY if n == i else th.LINE_STRONG, animate=200)
                   for n in range(len(SLIDES))], spacing=8, alignment=ft.MainAxisAlignment.CENTER)
    art = ft.Container(
        ft.Container(ft.Icon(icon, size=72, color=th.PRIMARY), width=150, height=150, bgcolor=th.SURFACE,
                     border_radius=44, alignment=ft.Alignment.CENTER, shadow=th.SHADOW),
        width=280, height=280, bgcolor=th.PRIMARY_TINT, border_radius=280, alignment=ft.Alignment.CENTER,
    )
    return ft.Container(ft.Column([
        ft.Row([_logo(), link_button("Pular", finish, th.INK_2)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Container(expand=True),
        ft.Row([art], alignment=ft.MainAxisAlignment.CENTER),
        ft.Container(height=24),
        T(title, 28, 800, text_align=ft.TextAlign.CENTER),
        T(text, 16, 400, th.INK_2, text_align=ft.TextAlign.CENTER),
        ft.Container(expand=True),
        dots,
        ft.Container(height=8),
        ft.Row([primary_button("Começar agora" if last else "Próximo",
                               finish if last else lambda e: app.go("onboarding", replace=True, i=i + 1),
                               ft.Icons.ARROW_FORWARD)]),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, expand=True),
        padding=ft.Padding.only(left=24, right=24, top=16, bottom=28), expand=True)


def consent_view(app):
    accepted = ft.Checkbox(value=False, active_color=th.PRIMARY)
    analytics = ft.Checkbox(value=False, active_color=th.PRIMARY)
    button = primary_button("Aceitar e continuar", disabled=True)

    def toggle(e):
        button.disabled = not accepted.value
        button.update()

    def accept(e):
        app.device.give_consent(analytics=bool(analytics.value))
        app.go("account", replace=True, first_run=True)

    accepted.on_change = toggle
    button.on_click = accept
    points = [
        (ft.Icons.PHONE_ANDROID, "Seus dados ficam no aparelho",
         "Medicações, doses e contatos são guardados localmente, sem conta e sem nuvem."),
        (ft.Icons.LOCK, "Você controla o acesso", "Proteja o app com PIN e veja quem acessou na auditoria."),
        (ft.Icons.FILE_DOWNLOAD, "Você leva seus dados", "Exporte backup e relatórios quando quiser."),
        (ft.Icons.SMART_TOY, "Assistente com IA é opcional",
         "Só envia a sua pergunta e os dados necessários à IA se você configurar uma chave de API."),
    ]
    return app.screen(None, [
        ft.Container(height=8),
        _logo(),
        T("Privacidade e consentimento", 26, 800),
        T("Dados de saúde são sensíveis (LGPD, art. 11). Antes de começar, veja como o MedRemind os trata:",
          15, 400, th.INK_2),
        card(ft.Column([ft.Row([icon_badge(i, size=40, radius=12),
                                ft.Column([T(t, 15, 700), T(s, 13, 400, th.INK_2)], spacing=2, expand=True)],
                               spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)
                        for i, t, s in points], spacing=16)),
        T("O MedRemind organiza lembretes e registros. Ele não substitui orientação médica.", 13, 600, th.INK_2),
        ft.Row([accepted, T("Li e aceito o tratamento dos meus dados de saúde para o funcionamento do app.",
                            14, 600, expand=True)], vertical_alignment=ft.CrossAxisAlignment.START),
        ft.Row([analytics, T("Opcional: compartilhar estatísticas anônimas de uso.", 14, 400, th.INK_2, expand=True)],
               vertical_alignment=ft.CrossAxisAlignment.START),
        ft.Row([button]),
    ])


class _PinPad:
    """Teclado numérico próprio (evita o teclado do sistema e funciona igual em todas as plataformas)."""

    def __init__(self, length: int, on_complete) -> None:
        self.length = length
        self.value = ""
        self.on_complete = on_complete
        self.dots = ft.Row(spacing=14, alignment=ft.MainAxisAlignment.CENTER)
        self._paint()

    def _paint(self):
        self.dots.controls = [ft.Container(width=16, height=16, border_radius=16,
                                           bgcolor=th.PRIMARY if n < len(self.value) else th.SURFACE,
                                           border=ft.Border.all(2, th.PRIMARY if n < len(self.value) else th.LINE_STRONG))
                              for n in range(self.length)]

    def reset(self):
        self.value = ""
        self._paint()
        self.dots.update()

    def press(self, key: str):
        if key == "del":
            self.value = self.value[:-1]
        elif len(self.value) < self.length:
            self.value += key
        self._paint()
        self.dots.update()
        if len(self.value) == self.length:
            self.on_complete(self.value)

    def keypad(self) -> ft.Column:
        def key(label: str, value: str | None = None, icon=None):
            v = value or label
            return ft.Container(
                ft.Icon(icon, color=th.INK) if icon else T(label, 26, 600),
                width=76, height=64, border_radius=20, alignment=ft.Alignment.CENTER,
                bgcolor=th.SURFACE if not icon else None, on_click=lambda e: self.press(v), ink=True,
                tooltip="Apagar" if icon else None,
            )
        rows = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]]
        out = [ft.Row([key(k) for k in r], spacing=16, alignment=ft.MainAxisAlignment.CENTER) for r in rows]
        out.append(ft.Row([ft.Container(width=76), key("0"), key("", "del", ft.Icons.BACKSPACE_OUTLINED)],
                          spacing=16, alignment=ft.MainAxisAlignment.CENTER))
        return ft.Column(out, spacing=12)


def lock_view(app):
    message = T("Digite seu PIN para entrar", 15, 500, th.INK_2, text_align=ft.TextAlign.CENTER)

    def done(pin: str):
        result = app.device.security.verify(pin)
        if result.ok:
            app.unlock()
            return
        message.value = result.message
        message.color = th.DANGER
        message.update()
        pad.reset()

    # O teclado usa o tamanho do PIN cadastrado (4 a 6 dígitos).
    stored = app.device.settings.get("pin_length", 4)
    length = stored if isinstance(stored, int) else 4
    pad = _PinPad(length, done)
    return ft.Container(ft.Column([
        ft.Container(expand=True),
        ft.Container(ft.Icon(ft.Icons.FINGERPRINT, size=56, color=th.PRIMARY), width=120, height=120,
                     border_radius=36, bgcolor=th.SURFACE, alignment=ft.Alignment.CENTER, shadow=th.SHADOW),
        T("Proteja seus dados", 26, 800, text_align=ft.TextAlign.CENTER),
        message,
        ft.Container(height=8),
        pad.dots,
        ft.Container(height=12),
        pad.keypad(),
        ft.Container(expand=True),
        ft.Container(ft.Row([ft.Icon(ft.Icons.VERIFIED_USER, size=16, color=th.SUCCESS_INK),
                             T("Dados protegidos no aparelho", 13, 700, th.SUCCESS_INK)], spacing=6, tight=True),
                     bgcolor=th.SUCCESS_TINT, border_radius=999, padding=ft.Padding.symmetric(horizontal=12, vertical=8)),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, expand=True),
        padding=ft.Padding.only(left=24, right=24, top=16, bottom=28), expand=True)


def pin_setup_view(app, first_run: bool = False, step: int = 1, first: str = ""):
    title = "Crie um PIN de acesso" if step == 1 else "Confirme o PIN"
    message = T("4 números que só você sabe." if step == 1 else "Digite o mesmo PIN de novo.",
                15, 500, th.INK_2, text_align=ft.TextAlign.CENTER)

    def done(pin: str):
        if step == 1:
            try:
                app.device.security.check_strength(pin)
            except ValueError as exc:
                message.value, message.color = str(exc), th.DANGER
                message.update()
                pad.reset()
                return
            app.go("pin_setup", replace=True, first_run=first_run, step=2, first=pin)
            return
        if pin != first:
            message.value, message.color = "Os PINs não conferem. Comece de novo.", th.DANGER
            message.update()
            app.go("pin_setup", replace=True, first_run=first_run, step=1)
            return
        app.device.security.set_pin(pin)
        app.device.settings.set("pin_length", len(pin))
        app.toast("PIN definido. O app pedirá o PIN ao abrir.")
        if first_run:
            app.unlock()
        else:
            app.back()

    pad = _PinPad(4, done)
    skip = link_button("Agora não", lambda e: app.unlock(), th.INK_2) if first_run else \
        link_button("Cancelar", app.back, th.INK_2)
    return ft.Container(ft.Column([
        ft.Row([skip], alignment=ft.MainAxisAlignment.END),
        ft.Container(expand=True),
        icon_badge(ft.Icons.LOCK, th.PRIMARY_TINT, th.PRIMARY, size=88, radius=28, icon_size=44),
        T(title, 26, 800, text_align=ft.TextAlign.CENTER),
        message,
        ft.Container(height=8),
        pad.dots,
        ft.Container(height=12),
        pad.keypad(),
        ft.Container(expand=True),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, expand=True),
        padding=ft.Padding.only(left=24, right=24, top=8, bottom=28), expand=True)

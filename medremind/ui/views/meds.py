"""Lista de medicações e formulário de cadastro/edição."""
from __future__ import annotations

from datetime import time, timedelta

import flet as ft

from ...core.models import WEEKDAY_LABELS, Frequency, Medication, MedForm
from ...core.services.medications import ValidationError
from ...core.services.text import normalize
from .. import theme as th
from ..components import (
    T,
    card,
    chip,
    empty_state,
    field,
    icon_badge,
    link_button,
    pill_toggle,
    primary_button,
    progress,
    secondary_button,
    switch_row,
    top_bar,
)

FORM_ICONS = {
    MedForm.COMPRIMIDO.value: ft.Icons.MEDICATION,
    MedForm.CAPSULA.value: ft.Icons.MEDICATION_OUTLINED,
    MedForm.LIQUIDO.value: ft.Icons.WATER_DROP,
    MedForm.INJECAO.value: ft.Icons.VACCINES,
    MedForm.GOTAS.value: ft.Icons.OPACITY,
}

FILTERS = [("all", "Todos"), ("active", "Ativos"), ("low", "Estoque baixo"), ("paused", "Pausados"), ("prn", "Se precisar")]


def _schedule_text(m: Medication) -> str:
    if m.frequency == Frequency.AS_NEEDED:
        return "Conforme necessário"
    times = ", ".join(t.strftime("%H:%M") for t in m.times)
    if m.frequency == Frequency.WEEKDAYS:
        return f"{', '.join(WEEKDAY_LABELS[d] for d in m.weekdays)} · {times}"
    return f"Todo dia · {times}"


def meds_view(app, filter: str = "all", query: str = ""):
    c = app.c
    statuses = {s.medication.id: s for s in c.meds.stock_overview()}
    meds = c.meds.list()

    def keep(m: Medication) -> bool:
        s = statuses.get(m.id)
        if query and normalize(query) not in normalize(m.name):
            return False
        return {
            "all": True,
            "active": not m.paused,
            "low": bool(s and s.low),
            "paused": m.paused,
            "prn": m.frequency == Frequency.AS_NEEDED,
        }[filter]

    shown = [m for m in meds if keep(m)]
    low_count = sum(1 for s in statuses.values() if s.low)
    subtitle = f"{len(meds)} tratamentos" + (f" · {low_count} para repor" if low_count else "")

    search = field("Buscar remédio", query, prefix_icon=ft.Icons.SEARCH,
                   on_submit=lambda e: app.go("meds", replace=True, filter=filter, query=e.control.value))

    chips = ft.Row([
        ft.Chip(label=T(label, 13, 700, "#FFFFFF" if key == filter else th.INK), selected=key == filter,
                show_checkmark=False, selected_color=th.INK, bgcolor=th.SURFACE,
                border_side=ft.BorderSide(1, th.INK if key == filter else th.LINE),
                on_select=lambda e, k=key: app.go("meds", replace=True, filter=k, query=query))
        for key, label in FILTERS
    ], wrap=True, spacing=8, run_spacing=8)

    items: list[ft.Control] = []
    for m in shown:
        s = statuses.get(m.id)
        if m.paused:
            st_chip = chip("Pausado", th.SURFACE_2, th.INK_2)
        elif s and s.empty:
            st_chip = chip("Sem estoque", th.DANGER_TINT, th.DANGER)
        elif s and s.low:
            st_chip = chip("Estoque baixo", th.WARN_TINT, th.WARN_INK)
        else:
            st_chip = chip("Ativo", th.SUCCESS_TINT, th.SUCCESS_INK)
        badge_colors = (th.WARN_TINT, th.WARN_INK) if s and s.low else \
            (th.SURFACE_2, th.INK_2) if m.paused else (th.PRIMARY_TINT, th.PRIMARY)
        rows: list[ft.Control] = [
            ft.Row([icon_badge(FORM_ICONS[m.form.value], *badge_colors, size=48, radius=16),
                    ft.Column([T(m.display_name, 17, 800), T(f"{m.dose_text} por dose", 14, 400, th.INK_2)], spacing=2, expand=True),
                    st_chip], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row([ft.Icon(ft.Icons.SCHEDULE, size=18, color=th.INK_2), T(_schedule_text(m), 14, 600, expand=True)],
                   spacing=8),
        ]
        if s is not None:
            days = f" · ~{int(s.days_left)} dias" if s.days_left is not None else ""
            fill = th.DANGER if s.empty else th.WARN if s.low else th.SUCCESS
            rows.append(ft.Column([
                ft.Row([T("Estoque", 13, 600, th.INK_2), T(f"{m.stock_units:g} de {m.stock_total:g}{days}", 13, 800)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                progress(s.ratio, fill),
            ], spacing=8))
        if m.frequency == Frequency.AS_NEEDED and not m.paused:
            def take_now(e, m=m):
                if not app.guard_write():
                    return
                c.schedule.take_as_needed(m.id)
                app.toast(f"Dose de {m.display_name} registrada")
                app.refresh()
            rows.append(ft.Row([secondary_button("Registrar dose agora", take_now, ft.Icons.CHECK, height=44)]))
        items.append(card(ft.Column(rows, spacing=14), on_click=lambda e, m=m: app.go("med_form", med_id=m.id)))

    if not shown:
        items.append(empty_state(ft.Icons.SEARCH_OFF, "Nenhum remédio neste filtro." if meds
                                 else "Você ainda não cadastrou remédios."))

    fab = ft.FloatingActionButton(content=ft.Row([ft.Icon(ft.Icons.ADD, color="#FFFFFF"), T("Adicionar", 15, 800, "#FFFFFF")],
                                                 spacing=6, tight=True),
                                  bgcolor=th.PRIMARY, width=148, on_click=lambda e: app.go("med_form"),
                                  shape=ft.RoundedRectangleBorder(radius=18))
    header = top_bar("Meus remédios", big=True, subtitle=subtitle,
                     actions=[link_button("Estoque", lambda e: app.go("stock"), icon=ft.Icons.INVENTORY_2)])
    return app.screen(header, [search, chips, *items], bottom=96), fab


class MedicationForm:
    """Formulário com estado próprio: atualiza só as partes que mudam."""

    def __init__(self, app, med: Medication | None) -> None:
        self.app = app
        self.editing = med is not None
        self.m = med or Medication(name="", times=[time(8, 0)], stock_units=0, stock_total=0)
        self.error = T("", 13, 700, th.DANGER, visible=False)

        m = self.m
        self.name = field("Nome da medicação", m.name, "Ex.: Losartana, Metformina", autofocus=not self.editing)
        self.strength = field("Concentração", m.strength, "Ex.: 500mg", expand=True)
        self.units = field("Qtd. por dose", f"{m.dose_units:g}", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
        self.instructions = field("Instruções", m.instructions, "Ex.: tomar com comida")
        self.stock = field("Unidades em casa", f"{m.stock_units:g}", keyboard_type=ft.KeyboardType.NUMBER, expand=True)
        self.alert_days = field("Avisar com (dias)", str(m.refill_alert_days), keyboard_type=ft.KeyboardType.NUMBER,
                                expand=True)
        self.duration_days = field("Duração (dias)", self._initial_duration(), keyboard_type=ft.KeyboardType.NUMBER)
        self.fixed_duration = m.end_date is not None

        self.form_box = ft.Container()
        self.freq_box = ft.Container()
        self.weekday_box = ft.Container()
        self.times_box = ft.Container()
        self.duration_box = ft.Container()
        self.stock_box = ft.Container()
        self._paint_all()

    def _initial_duration(self) -> str:
        m = self.m
        if m.end_date and m.start_date:
            return str((m.end_date - m.start_date).days + 1)
        return "7"

    # ------------------------------------------------------------- pintura
    def _paint_all(self):
        self._paint_form()
        self._paint_freq()
        self._paint_times()
        self._paint_duration()
        self._paint_stock()

    def _update(self, *controls):
        for ctl in controls:
            try:
                ctl.update()
            except RuntimeError:
                pass  # ainda não está na página (primeira pintura)

    def _paint_form(self):
        opts = [(f.value, f.label) for f in MedForm]
        self.form_box.content = pill_toggle(opts, self.m.form.value, self._set_form, icons=FORM_ICONS)
        self._update(self.form_box)

    def _set_form(self, v):
        self.m.form = MedForm(v)
        self._paint_form()

    def _paint_freq(self):
        opts = [(f.value, l) for f, l in [(Frequency.DAILY, "Todo dia"), (Frequency.WEEKDAYS, "Dias fixos"),
                                           (Frequency.AS_NEEDED, "Se precisar")]]
        self.freq_box.content = pill_toggle(opts, self.m.frequency.value, self._set_freq)
        wd = self.m.frequency == Frequency.WEEKDAYS
        self.weekday_box.visible = wd
        self.weekday_box.content = ft.Row([
            ft.Container(T(lbl[0], 14, 800, "#FFFFFF" if i in self.m.weekdays else th.INK), width=40, height=40,
                         border_radius=40, alignment=ft.Alignment.CENTER, tooltip=lbl,
                         bgcolor=th.PRIMARY if i in self.m.weekdays else th.SURFACE,
                         border=ft.Border.all(1, th.PRIMARY if i in self.m.weekdays else th.LINE),
                         on_click=lambda e, i=i: self._toggle_day(i))
            for i, lbl in enumerate(WEEKDAY_LABELS)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        self.times_box.visible = self.m.frequency != Frequency.AS_NEEDED
        self._update(self.freq_box, self.weekday_box, self.times_box)

    def _set_freq(self, v):
        self.m.frequency = Frequency(v)
        if self.m.frequency == Frequency.WEEKDAYS and not self.m.weekdays:
            self.m.weekdays = [0, 2, 4]
        self._paint_freq()

    def _toggle_day(self, i):
        days = set(self.m.weekdays)
        days.symmetric_difference_update({i})
        self.m.weekdays = sorted(days)
        self._paint_freq()

    def _paint_times(self):
        chips = [
            ft.Container(ft.Row([ft.Icon(ft.Icons.SCHEDULE, size=16, color=th.PRIMARY_DARK),
                                 T(t.strftime("%H:%M"), 15, 800, th.PRIMARY_DARK),
                                 ft.IconButton(ft.Icons.CLOSE, icon_size=16, icon_color=th.PRIMARY_DARK,
                                               tooltip="Remover horário", width=32, height=32,
                                               on_click=lambda e, t=t: self._remove_time(t))],
                                spacing=4, tight=True),
                         bgcolor=th.PRIMARY_TINT, border_radius=999, padding=ft.Padding.only(left=12, right=2))
            for t in sorted(self.m.times)
        ]
        chips.append(ft.OutlinedButton(content=T("Horário", 14, 700, th.PRIMARY), icon=ft.Icons.ADD,
                                       on_click=self._pick_time,
                                       style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=999))))
        self.times_box.content = ft.Column([T("Horários", 14, 700), ft.Row(chips, wrap=True, spacing=8, run_spacing=8)],
                                           spacing=8)
        self._update(self.times_box)

    def _remove_time(self, t):
        self.m.times = [x for x in self.m.times if x != t]
        self._paint_times()

    def _pick_time(self, e):
        def chosen(ev):
            value = ev.control.value
            if value is None:
                return
            t = time(value.hour, value.minute)
            if t not in self.m.times:
                self.m.times.append(t)
            self._paint_times()
        suggestion = (max(self.m.times).replace(hour=(max(self.m.times).hour + 8) % 24) if self.m.times else time(8, 0))
        self.app.page.show_dialog(ft.TimePicker(value=suggestion, on_change=chosen, help_text="Horário da dose",
                                                cancel_text="Cancelar", confirm_text="OK",
                                                hour_format=ft.TimePickerHourFormat.H24))

    def _paint_duration(self):
        self.duration_box.content = ft.Column([
            pill_toggle([("cont", "Uso contínuo"), ("fixed", "Por X dias")],
                        "fixed" if self.fixed_duration else "cont", self._set_duration),
            ft.Container(self.duration_days, visible=self.fixed_duration),
        ], spacing=10)
        self._update(self.duration_box)

    def _set_duration(self, v):
        self.fixed_duration = v == "fixed"
        self._paint_duration()

    def _paint_stock(self):
        self.stock_box.content = ft.Column([
            switch_row(ft.Icons.INVENTORY_2, "Acompanhar estoque", "Aviso quando estiver acabando",
                       self.m.track_stock, self._toggle_stock),
            ft.Row([self.stock, self.alert_days], spacing=12, visible=self.m.track_stock),
            switch_row(ft.Icons.NOTIFICATIONS_ACTIVE, "Lembretes", "Alerta no horário de cada dose",
                       self.m.reminders, lambda e: setattr(self.m, "reminders", e.control.value), last=True),
        ], spacing=8)
        self._update(self.stock_box)

    def _toggle_stock(self, e):
        self.m.track_stock = e.control.value
        self._paint_stock()

    # ---------------------------------------------------------------- salvar
    @staticmethod
    def _num(tf: ft.TextField, label: str, integer: bool = False) -> float:
        raw = (tf.value or "0").replace(",", ".").strip() or "0"
        try:
            value = float(raw)
        except ValueError:
            raise ValidationError(f"“{label}” precisa ser um número.") from None
        return int(value) if integer else value

    def save(self, e=None):
        if not self.app.guard_write():
            return
        m = self.m
        try:
            m.name = self.name.value or ""
            m.strength = self.strength.value or ""
            m.instructions = self.instructions.value or ""
            m.dose_units = self._num(self.units, "Qtd. por dose")
            if m.track_stock:
                new_stock = self._num(self.stock, "Unidades em casa")
                if not self.editing or new_stock != m.stock_units:
                    m.stock_total = max(new_stock, m.stock_total if self.editing else new_stock)
                m.stock_units = new_stock
                m.refill_alert_days = int(self._num(self.alert_days, "Avisar com", integer=True))
            if m.frequency == Frequency.AS_NEEDED:
                m.times = []
            start = m.start_date or self.app.c.schedule.clock().date()
            m.start_date = start
            if self.fixed_duration:
                days = int(self._num(self.duration_days, "Duração", integer=True))
                if days < 1:
                    raise ValidationError("A duração deve ser de pelo menos 1 dia.")
                m.end_date = start + timedelta(days=days - 1)
            else:
                m.end_date = None
            self.app.c.meds.save(m)
        except ValidationError as exc:
            self.error.value = str(exc)
            self.error.visible = True
            self.error.update()
            return
        self.app.toast("Medicação salva" if self.editing else f"{m.display_name} adicionada")
        self.app.back()

    def build(self):
        app = self.app
        sections: list[ft.Control] = [
            T("Editar medicação" if self.editing else "Adicionar medicação", 26, 800),
            T("Informe os detalhes para montar seus lembretes.", 15, 400, th.INK_2),
            card(ft.Column([self.name, T("Forma", 14, 700), self.form_box,
                            ft.Row([self.strength, self.units], spacing=12)], spacing=14)),
            card(ft.Column([T("Cronograma", 17, 800), self.freq_box, self.weekday_box, self.times_box,
                            T("Duração", 14, 700), self.duration_box], spacing=14)),
            card(ft.Column([self.instructions], spacing=8)),
            card(self.stock_box, padding=ft.Padding.symmetric(horizontal=18, vertical=6)),
            self.error,
            ft.Row([primary_button("Salvar medicação", self.save, ft.Icons.CHECK)]),
        ]
        if self.editing:
            m = self.m

            def toggle_pause(e):
                app.c.meds.set_paused(m.id, not m.paused)
                app.toast("Medicação reativada" if m.paused else "Medicação pausada — sem lembretes")
                app.back()

            def delete(e):
                app.confirm("Excluir medicação?", f"{m.display_name} e todo o histórico de doses serão apagados.",
                            lambda: (app.c.meds.delete(m.id), app.toast("Medicação excluída"), app.back()),
                            yes="Excluir", danger=True)

            sections.append(ft.Row([
                secondary_button("Reativar" if m.paused else "Pausar", toggle_pause,
                                 ft.Icons.PLAY_ARROW if m.paused else ft.Icons.PAUSE, height=48),
                secondary_button("Excluir", delete, ft.Icons.DELETE_OUTLINE, fg=th.DANGER, height=48,
                                 border_color="#F3C4BF"),
            ], spacing=10))
        header = top_bar("Medicação" if self.editing else "Nova medicação", on_back=app.back)
        return app.screen(header, sections)


def med_form_view(app, med_id: int | None = None):
    med = app.c.meds.get(med_id) if med_id else None
    return MedicationForm(app, med).build()

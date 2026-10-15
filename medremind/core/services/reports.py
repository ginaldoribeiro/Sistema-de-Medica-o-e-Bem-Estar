"""Relatórios para levar ao médico: CSV (planilha) e HTML pronto para imprimir/salvar em PDF."""
from __future__ import annotations

import csv
import html
import io
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from ..models import DoseStatus
from ..repositories import SettingsRepository
from .audit import AuditService
from .medications import MedicationService
from .schedule import ScheduleService


class ReportService:
    def __init__(self, schedule: ScheduleService, meds: MedicationService, settings: SettingsRepository,
                 audit: AuditService, clock: Callable[[], datetime] = datetime.now) -> None:
        self.schedule = schedule
        self.meds = meds
        self.settings = settings
        self.audit = audit
        self.clock = clock

    def _rows(self, start: date, end: date):
        day = start
        while day <= end:
            for d in self.schedule.doses_for_day(day):
                yield d
            day += timedelta(days=1)

    def csv_text(self, start: date, end: date) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["data", "horario_previsto", "medicacao", "dosagem", "status", "registrado_em"])
        for d in self._rows(start, end):
            w.writerow([
                d.scheduled_at.strftime("%d/%m/%Y"),
                d.scheduled_at.strftime("%H:%M"),
                d.medication.name,
                d.medication.strength,
                d.status.label,
                d.acted_at.strftime("%d/%m/%Y %H:%M") if d.acted_at else "",
            ])
        return buf.getvalue()

    def html_text(self, start: date, end: date) -> str:
        p = self.settings.profile()
        adh = self.schedule.adherence(start, end)
        e = html.escape
        meds_rows = "".join(
            f"<tr><td>{e(m.display_name)}</td><td>{e(m.form.label)}</td>"
            f"<td>{e(', '.join(t.strftime('%H:%M') for t in m.times) or m.frequency.label)}</td>"
            f"<td>{e(m.instructions)}</td><td>{'Pausada' if m.paused else 'Ativa'}</td></tr>"
            for m in self.meds.list()
        )
        missed = [d for d in self._rows(start, end) if d.status in (DoseStatus.MISSED, DoseStatus.SKIPPED)]
        missed_rows = "".join(
            f"<tr><td>{d.scheduled_at:%d/%m %H:%M}</td><td>{e(d.medication.display_name)}</td><td>{d.status.label}</td></tr>"
            for d in missed
        ) or '<tr><td colspan="3">Nenhuma dose perdida no período.</td></tr>'
        return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório MedRemind — {e(p.name)}</title>
<style>body{{font-family:system-ui,sans-serif;color:#121826;max-width:820px;margin:32px auto;padding:0 16px}}
h1{{font-size:24px}}table{{width:100%;border-collapse:collapse;margin:12px 0 28px}}
td,th{{border-bottom:1px solid #DDE2EC;padding:8px;text-align:left;font-size:14px}}
.kpi{{display:flex;gap:24px}}.kpi div{{background:#F6F7FB;border-radius:12px;padding:12px 16px}}
.kpi b{{display:block;font-size:24px}}</style></head><body>
<h1>Relatório de adesão ao tratamento</h1>
<p><b>Paciente:</b> {e(p.name or '—')} · <b>ID:</b> {e(p.health_id or '—')}<br>
<b>Período:</b> {start:%d/%m/%Y} a {end:%d/%m/%Y} · gerado em {self.clock():%d/%m/%Y %H:%M}</p>
<div class="kpi"><div><b>{adh.rate:.0%}</b>doses tomadas</div><div><b>{adh.on_time_rate:.0%}</b>no horário (±1 h)</div>
<div><b>{adh.due - adh.taken}</b>doses não tomadas</div></div>
<h2>Medicações</h2><table><tr><th>Medicação</th><th>Forma</th><th>Horários</th><th>Instruções</th><th>Situação</th></tr>{meds_rows}</table>
<h2>Doses perdidas ou puladas</h2><table><tr><th>Quando</th><th>Medicação</th><th>Status</th></tr>{missed_rows}</table>
<p style="font-size:12px;color:#4A5468">Gerado pelo MedRemind a partir dos registros do paciente. Não substitui avaliação médica.</p>
</body></html>"""

    def export(self, folder: str | Path, days: int = 30) -> tuple[Path, Path]:
        end = self.clock().date()
        start = end - timedelta(days=days - 1)
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = f"{self.clock():%Y%m%d-%H%M}"
        csv_path = folder / f"medremind-doses-{stamp}.csv"
        html_path = folder / f"medremind-relatorio-{stamp}.html"
        csv_path.write_text(self.csv_text(start, end), encoding="utf-8-sig")
        html_path.write_text(self.html_text(start, end), encoding="utf-8")
        self.audit.log("relatorio_gerado", f"{days} dias")
        return csv_path, html_path

"""Cadastro de medicações com validação e previsão de estoque."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from ..models import Frequency, Medication
from ..repositories import MedicationRepository
from .audit import AuditService


class ValidationError(ValueError):
    """Erro de validação com mensagem pronta para o usuário."""


@dataclass
class StockStatus:
    medication: Medication
    days_left: float | None     # None = não é possível prever (sem uso diário ou sem controle)
    runs_out_on: date | None
    low: bool
    empty: bool

    @property
    def ratio(self) -> float:
        m = self.medication
        if not m.stock_total:
            return 1.0 if m.stock_units else 0.0
        return max(0.0, min(1.0, m.stock_units / m.stock_total))


class MedicationService:
    def __init__(self, repo: MedicationRepository, audit: AuditService,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.repo = repo
        self.audit = audit
        self.clock = clock

    # ------------------------------------------------------------- validação
    @staticmethod
    def validate(m: Medication) -> None:
        if not m.name or not m.name.strip():
            raise ValidationError("Informe o nome da medicação.")
        if len(m.name) > 80:
            raise ValidationError("O nome deve ter no máximo 80 caracteres.")
        if m.dose_units <= 0:
            raise ValidationError("A quantidade por dose deve ser maior que zero.")
        if m.frequency != Frequency.AS_NEEDED and not m.times:
            raise ValidationError("Defina pelo menos um horário.")
        if len(set(m.times)) != len(m.times):
            raise ValidationError("Há horários repetidos.")
        if m.frequency == Frequency.WEEKDAYS and not m.weekdays:
            raise ValidationError("Escolha pelo menos um dia da semana.")
        if any(w not in range(7) for w in m.weekdays):
            raise ValidationError("Dia da semana inválido.")
        if m.end_date and m.start_date and m.end_date < m.start_date:
            raise ValidationError("A data de término é anterior ao início.")
        if m.stock_units < 0 or m.stock_total < 0:
            raise ValidationError("O estoque não pode ser negativo.")
        if m.refill_alert_days < 0:
            raise ValidationError("O aviso de reposição deve ser zero ou mais dias.")

    # ------------------------------------------------------------------ CRUD
    def list(self, include_paused: bool = True) -> list[Medication]:
        return self.repo.list(include_paused)

    def get(self, med_id: int) -> Medication | None:
        return self.repo.get(med_id)

    def find(self, text: str) -> list[Medication]:
        """Busca por nome ignorando acentos e maiúsculas."""
        from .text import normalize

        q = normalize(text)
        return [m for m in self.repo.list() if q and (q in normalize(m.name) or normalize(m.name) in q)]

    def save(self, m: Medication) -> Medication:
        if m.start_date is None:
            m.start_date = self.clock().date()
        if m.stock_total < m.stock_units:
            m.stock_total = m.stock_units
        self.validate(m)
        if m.id is None:
            self.repo.add(m)
            self.audit.log("medicacao_criada", m.display_name)
        else:
            self.repo.update(m)
            self.audit.log("medicacao_editada", m.display_name)
        return m

    def set_paused(self, med_id: int, paused: bool) -> None:
        m = self.repo.get(med_id)
        if m:
            m.paused = paused
            self.repo.update(m)
            self.audit.log("medicacao_editada", f"{m.display_name} {'pausada' if paused else 'reativada'}")

    def delete(self, med_id: int) -> None:
        m = self.repo.get(med_id)
        if m:
            self.repo.delete(med_id)
            self.audit.log("medicacao_removida", m.display_name)

    # ---------------------------------------------------------------- estoque
    def stock_status(self, m: Medication) -> StockStatus:
        empty = m.track_stock and m.stock_units < m.dose_units
        per_day = m.doses_per_day * m.dose_units
        if not m.track_stock or per_day == 0:
            return StockStatus(m, None, None, empty, empty)
        days_left = m.stock_units / per_day
        runs_out = self.clock().date() + timedelta(days=math.floor(days_left))
        low = days_left <= m.refill_alert_days
        return StockStatus(m, days_left, runs_out, low or empty, empty)

    def stock_overview(self) -> list[StockStatus]:
        """Todas as medicações com estoque controlado, as mais urgentes primeiro."""
        items = [self.stock_status(m) for m in self.repo.list() if m.track_stock]
        return sorted(items, key=lambda s: (not s.empty, not s.low, s.days_left if s.days_left is not None else 1e9))

    def refill(self, med_id: int, units: float) -> None:
        if units <= 0:
            raise ValidationError("Informe uma quantidade maior que zero.")
        m = self.repo.get(med_id)
        if m is None:
            raise ValidationError("Medicação não encontrada.")
        m.stock_units += units
        m.stock_total = max(m.stock_total, m.stock_units)
        self.repo.update(m)
        self.audit.log("estoque_reposto", f"{m.display_name} +{units:g}")

"""Assistente de voz/texto como agente com ferramentas.

Arquitetura
-----------
* ``AssistantTools`` expõe as capacidades do app como *ferramentas* (nome,
  descrição, JSON Schema e handler) — o mesmo contrato usado por LLMs com
  *tool use*.
* ``LocalAgent`` entende comandos em português por regras (funciona offline,
  sem custo e sem enviar dados para fora do aparelho).
* ``LLMAgent`` usa a API da Anthropic (Messages + tool use) quando existe a
  variável ``ANTHROPIC_API_KEY``. Se a chamada falhar, cai para o agente local.

Regras de segurança valem para os dois: o assistente não muda doses, não
recomenda remédios e encaminha emergências para o SAMU (192).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from ..models import DoseStatus, Medication
from ..repositories import ContactRepository
from .hydration import HydrationService
from .medications import MedicationService
from .schedule import ScheduleService
from .text import liters, normalize, plural

SAFETY_REPLY = (
    "Não posso orientar mudanças de dose, combinações ou novos remédios. "
    "Fale com seu médico ou farmacêutico — se quiser, abro seus contatos."
)
EMERGENCY_REPLY = (
    "Se for uma emergência, ligue agora para o SAMU: 192. "
    "Seus contatos de emergência estão no botão SOS da tela inicial."
)


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[..., str]


@dataclass
class AgentReply:
    text: str
    tools_used: list[str] = field(default_factory=list)
    changed_data: bool = False
    engine: str = "local"


class AssistantTools:
    MUTATING = {"registrar_dose_tomada", "registrar_agua"}

    def __init__(self, schedule: ScheduleService, meds: MedicationService,
                 hydration: HydrationService, contacts: ContactRepository) -> None:
        self.schedule = schedule
        self.meds = meds
        self.hydration = hydration
        self.contacts = contacts
        self.tools: dict[str, Tool] = {t.name: t for t in [
            Tool("listar_doses_hoje", "Lista as doses de hoje com horário e situação.",
                 {"type": "object", "properties": {}}, self.list_today),
            Tool("proxima_dose", "Informa a próxima dose a tomar.",
                 {"type": "object", "properties": {}}, self.next_dose),
            Tool("registrar_dose_tomada", "Registra que o usuário tomou a dose pendente de uma medicação.",
                 {"type": "object", "properties": {"medicacao": {"type": "string", "description": "Nome da medicação"}},
                  "required": ["medicacao"]}, self.mark_taken),
            Tool("consultar_estoque", "Mostra quanto resta de cada medicação e o que precisa de reposição.",
                 {"type": "object", "properties": {}}, self.stock),
            Tool("registrar_agua", "Registra água bebida, em mililitros.",
                 {"type": "object", "properties": {"ml": {"type": "integer", "minimum": 50, "maximum": 2000}},
                  "required": ["ml"]}, self.add_water),
            Tool("resumo_adesao", "Resume a adesão ao tratamento nos últimos dias.",
                 {"type": "object", "properties": {"dias": {"type": "integer", "minimum": 1, "maximum": 90}}},
                 self.adherence),
            Tool("contatos_emergencia", "Lista os contatos de emergência e médicos cadastrados.",
                 {"type": "object", "properties": {}}, self.emergency_contacts),
        ]}

    def call(self, name: str, args: dict | None = None) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"Ferramenta desconhecida: {name}"
        try:
            return tool.handler(**(args or {}))
        except TypeError as exc:
            return f"Parâmetros inválidos para {name}: {exc}"
        except ValueError as exc:
            return str(exc)

    # ---------------------------------------------------------------- handlers
    def list_today(self) -> str:
        doses = self.schedule.today()
        if not doses:
            return "Você não tem doses agendadas para hoje."
        lines = [f"• {d.scheduled_at:%H:%M} — {d.medication.display_name}: {d.status.label.lower()}" for d in doses]
        taken = sum(d.status == DoseStatus.TAKEN for d in doses)
        return f"Hoje você tem {len(doses)} doses ({taken} tomadas):\n" + "\n".join(lines)

    def next_dose(self) -> str:
        d = self.schedule.next_dose()
        if d is None:
            return "Não há próximas doses agendadas."
        when = d.snoozed_until or d.scheduled_at
        prefix = "Está na hora de" if d.status == DoseStatus.DUE else f"A próxima é às {when:%H:%M}:"
        extra = f" ({d.medication.instructions})" if d.medication.instructions else ""
        return f"{prefix} {d.medication.display_name}{extra}."

    def _match(self, text: str) -> list[Medication]:
        q = normalize(text)
        return [m for m in self.meds.list(include_paused=False)
                if normalize(m.name) in q or (len(q) >= 3 and q in normalize(m.name))]

    def mark_taken(self, medicacao: str) -> str:
        matches = self._match(medicacao)
        if not matches:
            return f"Não encontrei “{medicacao}” entre suas medicações ativas."
        if len(matches) > 1:
            return "Encontrei mais de uma: " + ", ".join(m.display_name for m in matches) + ". Qual delas?"
        med = matches[0]
        pending = [d for d in self.schedule.today() if d.medication.id == med.id
                   and d.status in (DoseStatus.DUE, DoseStatus.SNOOZED, DoseStatus.MISSED, DoseStatus.UPCOMING)]
        if not pending:
            if not med.times:
                self.schedule.take_as_needed(med.id)
                return f"Registrei uma dose de {med.display_name} agora."
            return f"Todas as doses de {med.display_name} de hoje já estão registradas."
        now = self.schedule.clock()
        dose = min(pending, key=lambda d: abs(d.scheduled_at - now))
        if dose.scheduled_at - now > timedelta(hours=3):
            return (f"A próxima dose de {med.display_name} é só às {dose.scheduled_at:%H:%M}. "
                    "Confirme no app se quiser registrar antes.")
        self.schedule.mark_taken(med.id, dose.scheduled_at)
        return f"Pronto! Registrei {med.display_name} das {dose.scheduled_at:%H:%M}."

    def stock(self) -> str:
        items = self.meds.stock_overview()
        if not items:
            return "Nenhuma medicação com controle de estoque."
        lines = []
        for s in items:
            m = s.medication
            days = f", dura cerca de {int(s.days_left)} dias" if s.days_left is not None else ""
            flag = " ⚠ repor" if s.low else ""
            lines.append(f"• {m.display_name}: {m.stock_units:g} unidades{days}{flag}")
        return "Estoque:\n" + "\n".join(lines)

    def add_water(self, ml: int) -> str:
        self.hydration.add(int(ml), "garrafa" if int(ml) >= 500 else "copo")
        day = self.hydration.today()
        return f"Anotei {int(ml)} ml. Hoje: {liters(day.total_ml)} de {liters(day.goal_ml)}."

    def adherence(self, dias: int = 7) -> str:
        end = self.schedule.clock().date()
        a = self.schedule.adherence(end - timedelta(days=dias - 1), end)
        if not a.due:
            return "Ainda não há doses suficientes para calcular a adesão."
        return (f"Nos últimos {dias} dias você tomou {a.taken} de {a.due} doses ({a.rate:.0%}); "
                f"{a.on_time_rate:.0%} no horário. Sequência atual: {plural(self.schedule.streak(), 'dia')}.")

    def emergency_contacts(self) -> str:
        cs = self.contacts.list()
        if not cs:
            return "Você ainda não cadastrou contatos de emergência. Em emergência, ligue 192 (SAMU)."
        return "Contatos:\n" + "\n".join(f"• {c.name} ({c.relation}) {c.phone}".rstrip() for c in cs)

    # --------------------------------------------------------- formato da API
    def anthropic_schema(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in self.tools.values()]


class LocalAgent:
    """Entende comandos curtos em português sem depender de internet."""

    WATER = re.compile(r"(\d{2,4})\s*(ml|mililitros?)|\b(um|1|dois|2)?\s*(copo|garrafa)s?\b")
    RISK = re.compile(r"(dobr|aument|diminu|reduz|parar de tomar|posso tomar|misturar|junto com|substitu|overdose)")
    EMERGENCY = re.compile(r"(emergencia|socorro|desmai|dor no peito|falta de ar|nao consigo respirar|samu)")

    def __init__(self, tools: AssistantTools) -> None:
        self.tools = tools

    def reply(self, message: str) -> AgentReply:
        q = normalize(message)
        used: list[str] = []

        def run(name: str, **args) -> str:
            used.append(name)
            return self.tools.call(name, args)

        if not q:
            text = "Pode falar! Ex.: “quais são meus remédios hoje?”"
        elif self.EMERGENCY.search(q):
            text = EMERGENCY_REPLY
        elif self.RISK.search(q):
            text = SAFETY_REPLY
        elif re.search(r"\b(bebi|agua|hidrat)", q) and (m := self.WATER.search(q)):
            if m.group(1):
                ml = int(m.group(1))
            else:
                qty = 2 if m.group(3) in ("dois", "2") else 1
                ml = qty * (500 if m.group(4) == "garrafa" else 200)
            text = run("registrar_agua", ml=ml)
        elif re.search(r"\b(tomei|ja tomei|tomado|registra|marca)\b", q):
            name = re.sub(r".*\b(tomei|ja tomei|tomado|registra|registrar|marca|marcar)\b( o| a| meu| minha)?", "", q).strip()
            text = run("registrar_dose_tomada", medicacao=name or q)
        elif re.search(r"\b(agua|hidrat)", q):
            day = self.tools.hydration.today()
            text = f"Hoje você bebeu {liters(day.total_ml)} de {liters(day.goal_ml)}."
        elif re.search(r"\b(proxim|qual a proxima|que horas)", q):
            text = run("proxima_dose")
        elif re.search(r"\b(estoque|acaband|repor|reposicao|comprar|sobr)", q):
            text = run("consultar_estoque")
        elif re.search(r"\b(adesao|como estou|desempenho|sequencia|progresso)", q):
            text = run("resumo_adesao", dias=7)
        elif re.search(r"\b(contato|medic[oa] de|ligar)", q):
            text = run("contatos_emergencia")
        elif re.search(r"\b(remedio|medicac|dose|hoje|tomar|agenda)", q):
            text = run("listar_doses_hoje")
        elif re.search(r"\b(ajuda|o que voce faz|comandos)", q):
            text = self.help()
        else:
            text = "Não entendi. " + self.help()
        return AgentReply(text, used, any(u in AssistantTools.MUTATING for u in used), "local")

    @staticmethod
    def help() -> str:
        return ("Posso: listar os remédios de hoje, dizer a próxima dose, registrar “tomei a aspirina”, "
                "anotar “bebi 300 ml”, consultar o estoque e resumir sua adesão.")


class LLMAgent:
    """Agente com a API da Anthropic (tool use). Usa só httpx, sem SDK obrigatório."""

    API_URL = "https://api.anthropic.com/v1/messages"
    MAX_STEPS = 5

    def __init__(self, tools: AssistantTools, api_key: str, model: str | None = None,
                 http_post: Callable[..., Any] | None = None) -> None:
        self.tools = tools
        self.api_key = api_key
        self.model = model or os.environ.get("MEDREMIND_LLM_MODEL", "claude-sonnet-5-5")
        self._post = http_post
        self.history: list[dict] = []

    def _system(self) -> str:
        now = self.tools.schedule.clock()
        return (
            "Você é o assistente do app MedRemind e conversa em português do Brasil, com frases curtas "
            "e acolhedoras (as respostas podem ser lidas em voz alta). Use as ferramentas para consultar "
            "e registrar dados — nunca invente horários, doses ou estoque. Regras de segurança: não "
            "recomende remédios, não altere doses nem diga se combinações são seguras; nesses casos "
            "oriente procurar o médico ou farmacêutico. Em sinais de emergência, diga para ligar 192 (SAMU). "
            f"Agora são {now:%H:%M} de {now:%d/%m/%Y}."
        )

    def _http(self, payload: dict) -> dict:
        if self._post is not None:
            return self._post(payload)
        import httpx

        r = httpx.post(self.API_URL, json=payload, timeout=30, headers={
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
        r.raise_for_status()
        return r.json()

    def reply(self, message: str) -> AgentReply:
        messages = self.history[-10:] + [{"role": "user", "content": message}]
        used: list[str] = []
        for _ in range(self.MAX_STEPS):
            data = self._http({
                "model": self.model,
                "max_tokens": 600,
                "system": self._system(),
                "tools": self.tools.anthropic_schema(),
                "messages": messages,
            })
            content = data.get("content", [])
            messages.append({"role": "assistant", "content": content})
            calls = [b for b in content if b.get("type") == "tool_use"]
            if data.get("stop_reason") != "tool_use" or not calls:
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
                # Guardamos só o texto da conversa; resultados de ferramentas não voltam ao contexto.
                self.history = self.history[-8:] + [{"role": "user", "content": message}, {"role": "assistant", "content": text or "…"}]
                return AgentReply(text or "Certo.", used, any(u in AssistantTools.MUTATING for u in used), "llm")
            results = []
            for call in calls:
                used.append(call["name"])
                output = self.tools.call(call["name"], call.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": call["id"], "content": output})
            messages.append({"role": "user", "content": results})
        return AgentReply("Não consegui concluir agora. Tente de novo.", used,
                          any(u in AssistantTools.MUTATING for u in used), "llm")


class Assistant:
    """Fachada: usa o LLM quando configurado e o agente local como reserva."""

    def __init__(self, tools: AssistantTools, api_key: str | None = None) -> None:
        self.tools = tools
        self.local = LocalAgent(tools)
        key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
        self.llm = LLMAgent(tools, key) if key else None

    @property
    def engine(self) -> str:
        return "IA (Claude)" if self.llm else "local (offline)"

    def reply(self, message: str) -> AgentReply:
        # Emergência e pedidos de risco são tratados localmente, sempre.
        q = normalize(message)
        if LocalAgent.EMERGENCY.search(q) or LocalAgent.RISK.search(q) or self.llm is None:
            return self.local.reply(message)
        try:
            return self.llm.reply(message)
        except Exception as exc:  # rede, chave inválida, limite de uso...
            fallback = self.local.reply(message)
            fallback.text += f"\n(Assistente offline: {type(exc).__name__})"
            return fallback


def tools_as_json(tools: AssistantTools) -> str:
    return json.dumps(tools.anthropic_schema(), ensure_ascii=False, indent=2)

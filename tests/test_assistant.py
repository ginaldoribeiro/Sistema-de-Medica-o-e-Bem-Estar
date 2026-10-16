from datetime import time

from medremind.core.models import DoseStatus, Medication
from medremind.core.services.assistant import AssistantTools, LLMAgent


def seed(c):
    c.meds.save(Medication("Aspirina", "81mg", times=[time(12, 30)], stock_units=10))
    c.meds.save(Medication("Atorvastatina", "40mg", times=[time(20, 0)], stock_units=3))


def test_local_agent_registers_dose_and_water(c):
    seed(c)
    r = c.assistant.reply("tomei a aspirina")
    assert r.changed_data and "Aspirina" in r.text
    assert c.schedule.today()[0].status == DoseStatus.TAKEN
    assert "200 ml" in c.assistant.reply("bebi um copo de água").text
    assert "300 ml" in c.assistant.reply("tomei 300 ml de água").text
    assert c.hydration.today().total_ml == 500


def test_local_agent_queries(c):
    seed(c)
    assert "2 doses" in c.assistant.reply("quais são meus remédios hoje?").text
    assert "Aspirina" in c.assistant.reply("qual a próxima dose?").text
    assert "repor" in c.assistant.reply("como está o estoque").text


def test_safety_rules_always_local(c):
    seed(c)
    assert "192" in c.assistant.reply("socorro, dor no peito").text
    r = c.assistant.reply("posso dobrar a dose da aspirina?")
    assert "médico" in r.text and not r.tools_used


def test_llm_agent_tool_loop_with_fake_api(c):
    seed(c)
    calls = []

    def fake_post(payload):
        calls.append(payload)
        if len(calls) == 1:
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "registrar_dose_tomada", "input": {"medicacao": "aspirina"}}]}
        assert payload["messages"][-1]["content"][0]["type"] == "tool_result"
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Feito, registrei sua aspirina."}]}

    tools = AssistantTools(c.schedule, c.meds, c.hydration, c.contacts)
    r = LLMAgent(tools, "fake-key", http_post=fake_post).reply("já tomei minha aspirina")
    assert r.engine == "llm" and r.tools_used == ["registrar_dose_tomada"] and r.changed_data
    assert c.schedule.today()[0].status == DoseStatus.TAKEN
    assert {t["name"] for t in calls[0]["tools"]} >= {"listar_doses_hoje", "registrar_agua"}

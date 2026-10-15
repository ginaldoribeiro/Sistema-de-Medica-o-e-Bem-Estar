import json
from datetime import time

import pytest

from medremind.core.container import Container
from medremind.core.models import Medication
from medremind.core.services.backup import BackupError


def test_pin_hash_never_plain_and_lockout(c, clock):
    c.security.set_pin("2580")
    stored = c.settings.get("pin")
    assert "2580" not in json.dumps(stored)
    assert c.security.verify("2580").ok
    for _ in range(5):
        r = c.security.verify("0000")
    assert not r.ok and r.locked_until is not None
    assert not c.security.verify("2580").ok  # bloqueado mesmo com o PIN certo
    clock.set(2026, 10, 14, 12, 31, 5)
    assert c.security.verify("2580").ok


@pytest.mark.parametrize("pin", ["1111", "1234", "12", "abcd", "9876"])
def test_weak_pins_rejected(c, pin):
    with pytest.raises(ValueError):
        c.security.set_pin(pin)


def test_backup_roundtrip_excludes_pin_and_detects_tampering(c, clock, tmp_path):
    c.meds.save(Medication("Aspirina", times=[time(8, 0)], stock_units=5))
    c.security.set_pin("2580")
    payload = c.backup.export_dict()
    assert "pin" not in {r["key"] for r in payload["data"]["settings"]}

    other = Container.build(":memory:", clock=clock, api_key="")
    counts = other.backup.import_dict(json.loads(json.dumps(payload)))
    assert counts["medications"] == 1 and other.meds.list()[0].name == "Aspirina"

    payload["data"]["medications"][0]["name"] = "Alterado"
    with pytest.raises(BackupError, match="integridade"):
        other.backup.import_dict(payload)

    path = c.backup.export_file(tmp_path)
    assert other.backup.import_file(path)["medications"] == 1


def test_audit_records_actions(c):
    c.meds.save(Medication("Aspirina", times=[time(8, 0)]))
    events = [a.event for a in c.audit.recent()]
    assert "medicacao_criada" in events


def test_reports(c, tmp_path):
    c.meds.save(Medication("Aspirina", "81mg", times=[time(8, 0)]))
    csv_path, html_path = c.reports.export(tmp_path, 7)
    assert "Aspirina" in csv_path.read_text(encoding="utf-8-sig")
    assert "Relatório de adesão" in html_path.read_text(encoding="utf-8")


def test_reminders_notify_once_and_repeat_when_persistent(c, clock):
    c.meds.save(Medication("Aspirina", times=[time(12, 30)]))
    assert len(c.reminders.poll()) == 1
    assert c.reminders.poll() == []
    c.reminders.save_prefs(persistent=True, repeat_minutes=5)
    clock.set(2026, 10, 14, 12, 36)
    assert c.reminders.poll()[0].repeat

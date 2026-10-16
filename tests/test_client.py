"""Cliente do app (CloudSession + ApiClient) falando com o backend real em memória."""
from __future__ import annotations

from datetime import time

import pytest
from fastapi.testclient import TestClient

from backend import security
from backend.config import Settings
from backend.db import DB
from backend.main import create_app
from medremind.client.api import ApiError
from medremind.client.session import CloudSession
from medremind.core.models import Medication

security._N = 2 ** 10


@pytest.fixture
def http():
    settings = Settings(database_url="sqlite://", scheduler_enabled=False, jwt_secret="x" * 48)
    return TestClient(create_app(settings, DB(settings.database_url)))


def session(tmp_path, http, name):
    return CloudSession(tmp_path / name, server_url="http://testserver", http=http)


def test_two_devices_same_account_and_logout_wipes_cache(tmp_path, http):
    phone = session(tmp_path, http, "celular")
    phone.register("maria@exemplo.com", "senha1234", "Maria Souza")
    assert phone.logged_in and phone.active.role == "owner"
    phone.container().meds.save(Medication("Losartana", "50mg", times=[time(8, 0)], stock_units=30))
    assert phone.sync().pushed == 1

    tablet = session(tmp_path, http, "tablet")
    tablet.login("maria@exemplo.com", "senha1234")
    assert tablet.sync().ok
    assert [m.name for m in tablet.container().meds.list()] == ["Losartana"]

    # A sessão sobrevive a reinício do app (tokens salvos com permissão restrita)
    again = session(tmp_path, http, "tablet")
    assert again.logged_in and again.user["name"] == "Maria Souza"

    tablet.logout()
    assert not tablet.logged_in
    assert not (tmp_path / "tablet" / "cache").exists()


def test_caregiver_follows_patient_and_read_only_changes_are_reverted(tmp_path, http):
    pat = session(tmp_path, http, "paciente")
    pat.register("joao@exemplo.com", "senha1234", "Seu João")
    pat.container().meds.save(Medication("Metformina", "500mg", times=[time(8, 0)], stock_units=60))
    pat.sync()

    doc = session(tmp_path, http, "medica")
    doc.register("ana@exemplo.com", "senha1234", "Dra. Ana", "doctor")
    code = pat.api.create_invite(pat.active.id, "doctor", can_edit=False)["code"]
    res = doc.api.accept_invite(code)
    doc.refresh_patients()
    ref = doc.switch(res["patient_id"])
    assert ref.name == "Seu João" and not ref.can_write and doc.follows_others

    assert doc.sync().ok
    meds = doc.container().meds.list()
    assert [m.name for m in meds] == ["Metformina"]

    # Mesmo que o app deixe gravar no cache, o servidor recusa e o cliente desfaz.
    m = meds[0]
    m.instructions = "alterado sem permissão"
    doc.container().meds.save(m)
    result = doc.sync()
    assert result.rejected and doc.container().meds.list()[0].instructions == ""
    assert doc.pending() == 0

    dash = doc.api.dashboard()
    assert dash[0]["name"] == "Seu João"


def test_wrong_password_and_offline_server(tmp_path, http):
    s = session(tmp_path, http, "x")
    s.register("ze@exemplo.com", "senha1234", "Zé")
    s.logout()
    with pytest.raises(ApiError) as err:
        s.login("ze@exemplo.com", "outra1234")
    assert err.value.status == 401

    off = CloudSession(tmp_path / "off", server_url="http://127.0.0.1:9")  # porta fechada
    with pytest.raises(ApiError) as err2:
        off.login("ze@exemplo.com", "senha1234")
    assert err2.value.status == 0  # OfflineError

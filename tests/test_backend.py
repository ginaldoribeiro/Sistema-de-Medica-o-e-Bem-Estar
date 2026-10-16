"""Testes do backend: autenticação, permissões, recursos, sincronização, alertas e LGPD."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import security
from backend.config import Settings
from backend.db import DB
from backend.main import create_app
from backend.notifications import scan_all

security._N = 2 ** 10  # hash rápido nos testes
API = "/api/v1"


@pytest.fixture
def server():
    """SQLite em memória por padrão; defina TEST_DATABASE_URL para rodar contra PostgreSQL."""
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    settings = Settings(database_url=url, scheduler_enabled=False, jwt_secret="teste" * 10)
    db = DB(settings.database_url)
    if not settings.is_sqlite:
        from backend.db import Base
        Base.metadata.drop_all(db.engine)
        db.create_all()
    app = create_app(settings, db)
    yield TestClient(app), db
    db.engine.dispose()


def register(client, email, name="Fulano", kind="patient", password="senha1234"):
    r = client.post(f"{API}/auth/register", json={"email": email, "password": password, "name": name,
                                                  "account_type": kind, "accept_terms": True})
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get(f"{API}/auth/me", headers=h).json()
    return h, me["patient_id"], r.json()


def med_body(name="Aspirina", times=("08:00",), stock=10):
    return {"name": name, "strength": "81mg", "times": list(times), "stock_units": stock, "stock_total": 30,
            "start_date": (datetime.now() - timedelta(days=3)).date().isoformat()}


# ---------------------------------------------------------------------- auth
def test_register_login_refresh_rotation(server):
    c, _ = server
    _, _, tokens = register(c, "ana@exemplo.com")
    assert c.post(f"{API}/auth/register", json={"email": "ANA@exemplo.com", "password": "outra1234", "name": "Xx",
                                                "accept_terms": True}).status_code == 409
    assert c.post(f"{API}/auth/login", json={"email": "ana@exemplo.com", "password": "errada123"}).status_code == 401
    ok = c.post(f"{API}/auth/login", json={"email": "ana@exemplo.com", "password": "senha1234"})
    assert ok.status_code == 200

    r1 = c.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    # Reusar o token antigo revoga a família inteira (proteção contra roubo de token)
    assert c.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert c.post(f"{API}/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 401


def test_register_validation(server):
    c, _ = server
    base = {"email": "b@exemplo.com", "name": "Bia", "accept_terms": True}
    assert c.post(f"{API}/auth/register", json={**base, "password": "12345678"}).status_code == 422
    assert c.post(f"{API}/auth/register", json={**base, "password": "abc12345", "accept_terms": False}).status_code == 422
    assert c.get(f"{API}/me/patients").status_code == 401


def test_login_rate_limited(server):
    c, _ = server
    register(c, "rl@exemplo.com")
    codes = [c.post(f"{API}/auth/login", json={"email": "rl@exemplo.com", "password": "x" * 8}).status_code
             for _ in range(11)]
    assert codes[-1] == 429


# ------------------------------------------------------------- recursos e doses
def test_medications_doses_and_stock(server):
    c, _ = server
    h, pid, _ = register(c, "p@exemplo.com", "Paciente")
    r = c.post(f"{API}/patients/{pid}/medications", headers=h, json=med_body(times=("00:00",)))
    assert r.status_code == 201
    med = r.json()
    assert med["dose_text"] == "1 comprimido" and med["stock"]["days_left"] == 10

    bad = c.post(f"{API}/patients/{pid}/medications", headers=h, json={**med_body(), "times": []})
    assert bad.status_code == 422 and "horário" in bad.json()["detail"]

    doses = c.get(f"{API}/patients/{pid}/doses", headers=h).json()
    at = doses[0]["scheduled_at"]
    for _ in range(2):  # idempotente
        c.post(f"{API}/patients/{pid}/doses/action", headers=h,
               json={"medication_id": med["id"], "scheduled_at": at, "action": "take"})
    assert c.get(f"{API}/patients/{pid}/medications/{med['id']}", headers=h).json()["stock_units"] == 9
    ov = c.get(f"{API}/patients/{pid}", headers=h).json()
    assert ov["progress"]["taken"] == 1 and ov["access"]["role"] == "owner"
    assert "Aspirina" in c.get(f"{API}/patients/{pid}/reports/doses.csv", headers=h).text
    assert c.post(f"{API}/patients/{pid}/water", headers=h, json={"amount_ml": 300}).json()["total_ml"] == 300
    assert "Aspirina" in c.post(f"{API}/patients/{pid}/assistant", headers=h,
                                json={"message": "quais são meus remédios hoje?"}).json()["reply"]


# ------------------------------------------------------- equipe e permissões
def test_care_team_permissions(server):
    c, _ = server
    hp, pid, _ = register(c, "pac@exemplo.com", "Dona Maria")
    hc, _, _ = register(c, "cui@exemplo.com", "Carlos", "caregiver")
    hd, _, _ = register(c, "med@exemplo.com", "Dra. Ana", "doctor")
    hx, _, _ = register(c, "x@exemplo.com", "Estranho")
    med = c.post(f"{API}/patients/{pid}/medications", headers=hp, json=med_body()).json()

    # Estranho não vê nem sabe se existe
    assert c.get(f"{API}/patients/{pid}/medications", headers=hx).status_code == 404

    code_c = c.post(f"{API}/patients/{pid}/invites", headers=hp, json={"role": "caregiver", "can_edit": True}).json()["code"]
    code_d = c.post(f"{API}/patients/{pid}/invites", headers=hp, json={"role": "doctor"}).json()["code"]
    assert c.post(f"{API}/patients/{pid}/invites", headers=hc, json={"role": "doctor"}).status_code in (403, 404)
    assert c.post(f"{API}/invites/accept", headers=hc, json={"code": code_c}).json()["can_write"] is True
    assert c.post(f"{API}/invites/accept", headers=hd, json={"code": code_d.lower()}).status_code == 200
    assert c.post(f"{API}/invites/accept", headers=hx, json={"code": code_d}).status_code == 404  # já usado

    # Médico lê, mas não escreve
    assert c.get(f"{API}/patients/{pid}/medications", headers=hd).status_code == 200
    assert c.delete(f"{API}/patients/{pid}/medications/{med['id']}", headers=hd).status_code == 403
    ro = c.post(f"{API}/patients/{pid}/assistant", headers=hd, json={"message": "tomei a aspirina"}).json()
    assert "somente leitura" in ro["reply"]
    # Cuidador com edição escreve
    assert c.post(f"{API}/patients/{pid}/water", headers=hc, json={"amount_ml": 200}).status_code == 201

    team = c.get(f"{API}/patients/{pid}/care-team", headers=hp).json()
    assert {m["role"] for m in team["members"]} == {"caregiver", "doctor"}
    assert len(c.get(f"{API}/me/patients", headers=hd).json()) == 2  # o próprio + Dona Maria
    dash = c.get(f"{API}/me/dashboard", headers=hd).json()
    assert dash[0]["name"] == "Dona Maria" and dash[0]["risk"] in ("alto", "medio", "baixo")

    # Paciente remove o médico; acesso some na hora
    doc = next(m for m in team["members"] if m["role"] == "doctor")
    assert c.delete(f"{API}/patients/{pid}/care-team/{doc['id']}", headers=hp).status_code == 204
    assert c.get(f"{API}/patients/{pid}/medications", headers=hd).status_code == 404
    # Auditoria só para o dono
    assert c.get(f"{API}/patients/{pid}/audit", headers=hc).status_code == 403
    events = {e["event"] for e in c.get(f"{API}/patients/{pid}/audit", headers=hp).json()}
    assert {"convite_aceito", "acesso_removido", "medicacao_criada"} <= events


# ------------------------------------------------------------------- sincronização
def test_sync_two_devices_last_write_wins(server, tmp_path):
    from medremind.core.container import Container
    from medremind.core.models import Medication
    from medremind.core.sync import SyncEngine
    from datetime import time

    c, _ = server
    h, pid, _ = register(c, "sync@exemplo.com")

    class Transport:
        def sync(self, patient_id, cursor, changes):
            r = c.post(f"{API}/patients/{patient_id}/sync", headers=h, json={"cursor": cursor, "changes": changes})
            assert r.status_code == 200, r.text
            return r.json()

    a = Container.build(tmp_path / "a.db", api_key="")
    b = Container.build(tmp_path / "b.db", api_key="")
    ea, eb = SyncEngine(a.db, Transport(), pid), SyncEngine(b.db, Transport(), pid)

    m = a.meds.save(Medication("Losartana", "50mg", times=[time(0, 0)], stock_units=20))
    a.hydration.add(250)
    assert ea.sync().pushed == 2
    assert eb.sync().ok
    assert [x.name for x in b.meds.list()] == ["Losartana"]
    assert b.hydration.today().total_ml == 250

    # B registra a dose; A recebe com o vínculo certo (ids locais diferentes)
    mb = b.meds.list()[0]
    b.schedule.mark_taken(mb.id, datetime.combine(datetime.now().date(), time(0, 0)))
    eb.sync()
    ea.sync()
    assert a.schedule.today()[0].status.value == "taken"
    assert a.meds.get(m.id).stock_units == 19

    # Edição concorrente: vence a mais recente
    ma = a.meds.get(m.id)
    ma.instructions = "versão A"
    a.meds.save(ma)
    import time as _time
    _time.sleep(0.01)
    mb = b.meds.list()[0]
    mb.instructions = "versão B (mais nova)"
    b.meds.save(mb)
    ea.sync()
    eb.sync()
    ea.sync()
    assert a.meds.get(m.id).instructions == b.meds.list()[0].instructions == "versão B (mais nova)"

    # Exclusão também viaja
    a.meds.delete(m.id)
    ea.sync()
    eb.sync()
    assert b.meds.list() == []
    assert ea.store.pending_count() == 0

    # O servidor enxerga os mesmos dados pela API REST
    assert c.get(f"{API}/patients/{pid}/medications", headers=h).json() == []


def test_sync_rejects_writes_from_read_only_member(server):
    c, _ = server
    hp, pid, _ = register(c, "dono@exemplo.com")
    hd, _, _ = register(c, "doc@exemplo.com", kind="doctor")
    code = c.post(f"{API}/patients/{pid}/invites", headers=hp, json={"role": "doctor"}).json()["code"]
    c.post(f"{API}/invites/accept", headers=hd, json={"code": code})
    r = c.post(f"{API}/patients/{pid}/sync", headers=hd, json={"cursor": 0, "changes": {"medications": [
        {"uuid": "a" * 32, "updated_at": "2030-01-01T00:00:00.000", "deleted": False, "name": "X", "form": "comprimido",
         "frequency": "daily", "times": ["08:00"]}]}}).json()
    assert r["rejected"][0]["reason"] == "somente leitura"
    assert c.get(f"{API}/patients/{pid}/medications", headers=hp).json() == []


# ------------------------------------------------------------ alertas e LGPD
def test_alerts_for_missed_dose_and_low_stock(server):
    c, db = server
    hp, pid, _ = register(c, "al@exemplo.com", "Seu João")
    hc, _, _ = register(c, "fi@exemplo.com", "Filha", "caregiver")
    code = c.post(f"{API}/patients/{pid}/invites", headers=hp, json={"role": "caregiver"}).json()["code"]
    c.post(f"{API}/invites/accept", headers=hc, json={"code": code})
    c.post(f"{API}/patients/{pid}/medications", headers=hp, json=med_body("Insulina", ("00:00",), stock=1))

    with db.Session() as s, s.begin():
        first = scan_all(s)
    with db.Session() as s, s.begin():
        again = scan_all(s)
    assert first >= 2 and again == 0  # sem duplicar

    notes = c.get(f"{API}/me/notifications", headers=hc).json()
    kinds = {n["kind"] for n in notes["items"]}
    if datetime.now().hour >= 2:  # a dose de 00:00 só é "perdida" depois da janela de 2 h
        assert "dose_perdida" in kinds
    assert "estoque_baixo" in kinds and notes["unread"] >= 1
    c.post(f"{API}/me/notifications/read-all", headers=hc)
    assert c.get(f"{API}/me/notifications", headers=hc).json()["unread"] == 0


def test_export_and_delete_account(server):
    c, _ = server
    h, pid, _ = register(c, "lgpd@exemplo.com", "Titular")
    c.post(f"{API}/patients/{pid}/medications", headers=h, json=med_body())
    data = c.get(f"{API}/me/export", headers=h).json()
    assert data["account"]["email"] == "lgpd@exemplo.com"
    assert data["patient"]["data"]["medications"][0]["name"] == "Aspirina"
    assert c.request("DELETE", f"{API}/me", headers=h, json={"password": "errada99", "confirm": "EXCLUIR"}).status_code == 400
    assert c.request("DELETE", f"{API}/me", headers=h, json={"password": "senha1234", "confirm": "EXCLUIR"}).status_code == 204
    assert c.post(f"{API}/auth/login", json={"email": "lgpd@exemplo.com", "password": "senha1234"}).status_code == 401


def test_health_and_security_headers(server):
    c, _ = server
    r = c.get("/health")
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff"
    assert c.get("/ready").json()["status"] == "ready"

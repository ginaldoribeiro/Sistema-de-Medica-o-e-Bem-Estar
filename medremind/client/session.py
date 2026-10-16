"""Sessão na nuvem: conta, pacientes acessíveis e um cache local por paciente.

Cada paciente tem o próprio banco SQLite em ``<dados>/cache/<id>.db``. As telas
continuam usando o mesmo ``Container`` do modo offline; o ``SyncEngine`` leva as
alterações para o servidor e traz as dos outros aparelhos e da equipe de cuidado.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..core.container import Container
from ..core.sync import SyncEngine, SyncResult
from .api import ApiClient, ApiError, OfflineError, TokenStore

DEFAULT_SERVER = os.environ.get("MEDREMIND_SERVER_URL", "http://localhost:8000")
ROLE_LABEL = {"owner": "Você", "caregiver": "Cuidador(a)", "doctor": "Médico(a)"}


@dataclass
class PatientRef:
    id: str
    name: str
    role: str        # owner | caregiver | doctor
    can_write: bool

    @property
    def role_label(self) -> str:
        return ROLE_LABEL.get(self.role, self.role)


class CloudSession:
    def __init__(self, data_dir: Path, server_url: str | None = None, http: httpx.Client | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.store = TokenStore(self.data_dir / "session.json")
        url = server_url or self.store.get("server_url") or DEFAULT_SERVER
        self.api = ApiClient(url, self.store, http=http)
        self._containers: dict[str, Container] = {}
        self._engines: dict[str, SyncEngine] = {}

    # --------------------------------------------------------------- estado
    @property
    def server_url(self) -> str:
        return self.api.base_url

    def set_server(self, url: str, http: httpx.Client | None = None) -> None:
        self.api = ApiClient(url.strip() or DEFAULT_SERVER, self.store, http=http)
        self.store.update(server_url=self.api.base_url)

    @property
    def logged_in(self) -> bool:
        return bool(self.store.get("refresh_token"))

    @property
    def user(self) -> dict:
        return self.store.get("user") or {}

    @property
    def patients(self) -> list[PatientRef]:
        return [PatientRef(**p) for p in self.store.get("patients") or []]

    @property
    def active(self) -> PatientRef | None:
        pid = self.store.get("active_patient")
        return next((p for p in self.patients if p.id == pid), None) or (self.patients[0] if self.patients else None)

    @property
    def follows_others(self) -> bool:
        return any(p.role != "owner" for p in self.patients)

    # ---------------------------------------------------------------- conta
    def _after_auth(self, me: dict) -> None:
        self.store.update(user=me, active_patient=me.get("patient_id"))
        self.refresh_patients()
        # Cuidadores e profissionais abrem direto em quem acompanham.
        others = [p for p in self.patients if p.role != "owner"]
        if me.get("account_type") in ("caregiver", "doctor") and others:
            self.store.update(active_patient=others[0].id)

    @property
    def is_professional(self) -> bool:
        return self.user.get("account_type") in ("caregiver", "doctor")

    def register(self, email: str, password: str, name: str, account_type: str = "patient",
                 professional_id: str = "") -> None:
        self._after_auth(self.api.register(email.strip(), password, name.strip(), account_type, professional_id))

    def login(self, email: str, password: str) -> None:
        self._after_auth(self.api.login(email.strip(), password))

    def refresh_patients(self) -> list[PatientRef]:
        try:
            items = self.api.patients()
        except OfflineError:
            return self.patients  # usa a lista salva
        self.store.update(patients=items)
        return self.patients

    def logout(self, wipe_cache: bool = True) -> None:
        self.api.logout()
        for c in self._containers.values():
            c.db.close()
        self._containers.clear()
        self._engines.clear()
        server = self.server_url
        self.store.clear()
        self.store.update(server_url=server)
        if wipe_cache:  # dados de saúde não ficam no aparelho depois de sair
            shutil.rmtree(self.data_dir / "cache", ignore_errors=True)

    def delete_account(self, password: str) -> None:
        self.api.delete_account(password)
        self.logout()

    # ---------------------------------------------------- paciente e cache
    def switch(self, patient_id: str) -> PatientRef:
        ref = next((p for p in self.patients if p.id == patient_id), None)
        if ref is None:
            raise ApiError(404, "Paciente não encontrado")
        self.store.update(active_patient=patient_id)
        return ref

    def container(self, patient_id: str | None = None, clock=None) -> Container:
        pid = patient_id or self.active.id
        if pid not in self._containers:
            path = self.data_dir / "cache" / f"{pid}.db"
            c = Container.build(path, **({"clock": clock} if clock else {}))
            c.settings.set("onboarded", True)
            if not c.consent_given:
                c.give_consent()  # o aceite foi feito no cadastro da conta
            self._containers[pid] = c
        return self._containers[pid]

    def engine(self, patient_id: str | None = None) -> SyncEngine:
        pid = patient_id or self.active.id
        if pid not in self._engines:
            self._engines[pid] = SyncEngine(self.container(pid).db, self.api, pid)
        return self._engines[pid]

    def sync(self, patient_id: str | None = None) -> SyncResult:
        if not self.logged_in or not self.patients:
            return SyncResult(False, error="Sem sessão")
        result = self.engine(patient_id).sync()
        if not result.ok and "Sessão expirada" in result.error:
            self.store.update(access_token=None)
        return result

    def pending(self, patient_id: str | None = None) -> int:
        return self.engine(patient_id).store.pending_count() if self.patients else 0

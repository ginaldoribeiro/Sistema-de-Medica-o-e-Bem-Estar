"""Cliente HTTP da API do MedRemind, com renovação automática da sessão."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

API = "/api/v1"


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class OfflineError(ApiError):
    def __init__(self, message: str = "Sem conexão com o servidor.") -> None:
        super().__init__(0, message)


class TokenStore:
    """Sessão salva em arquivo com permissão restrita (0600)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.data = {}

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def update(self, **values) -> None:
        self.data.update(values)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, default=str), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    def clear(self) -> None:
        self.data = {}
        self.path.unlink(missing_ok=True)


class ApiClient:
    def __init__(self, base_url: str, tokens: TokenStore, http: httpx.Client | None = None,
                 timeout: float = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.tokens = tokens
        self.http = http or httpx.Client(base_url=self.base_url, timeout=timeout,
                                         headers={"User-Agent": "MedRemind-App/2.0"})

    # ----------------------------------------------------------------- núcleo
    def _send(self, method: str, path: str, auth: bool, **kw) -> httpx.Response:
        headers = kw.pop("headers", {})
        if auth and self.tokens.get("access_token"):
            headers["Authorization"] = f"Bearer {self.tokens.get('access_token')}"
        url = path if path.startswith("/") else f"/{path}"
        try:
            return self.http.request(method, url, headers=headers, **kw)
        except httpx.TransportError as exc:
            raise OfflineError() from exc

    def request(self, method: str, path: str, auth: bool = True, **kw) -> Any:
        r = self._send(method, path, auth, **kw)
        if r.status_code == 401 and auth and self.tokens.get("refresh_token") and self._refresh():
            r = self._send(method, path, auth, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ApiError(r.status_code, detail if isinstance(detail, str) else str(detail))
        if r.status_code == 204 or not r.content:
            return None
        ctype = r.headers.get("content-type", "")
        return r.json() if "json" in ctype else r.text

    def _refresh(self) -> bool:
        r = self._send("POST", f"{API}/auth/refresh", False, json={"refresh_token": self.tokens.get("refresh_token")})
        if r.status_code != 200:
            self.tokens.update(access_token=None, refresh_token=None)
            return False
        self._store(r.json())
        return True

    def _store(self, tokens: dict) -> None:
        self.tokens.update(access_token=tokens["access_token"], refresh_token=tokens["refresh_token"],
                           server_url=self.base_url)

    # ----------------------------------------------------------------- conta
    def register(self, email: str, password: str, name: str, account_type: str = "patient",
                 professional_id: str = "") -> dict:
        tokens = self.request("POST", f"{API}/auth/register", auth=False, json={
            "email": email, "password": password, "name": name, "account_type": account_type,
            "professional_id": professional_id, "accept_terms": True})
        self._store(tokens)
        return self.me()

    def login(self, email: str, password: str) -> dict:
        self._store(self.request("POST", f"{API}/auth/login", auth=False, json={"email": email, "password": password}))
        return self.me()

    def logout(self) -> None:
        if self.tokens.get("refresh_token"):
            try:
                self.request("POST", f"{API}/auth/logout", auth=False,
                             json={"refresh_token": self.tokens.get("refresh_token")})
            except ApiError:
                pass

    def me(self) -> dict:
        return self.request("GET", f"{API}/auth/me")

    def change_password(self, current: str, new: str) -> None:
        self.request("POST", f"{API}/auth/change-password", json={"current_password": current, "new_password": new})

    def patients(self) -> list[dict]:
        return self.request("GET", f"{API}/me/patients")

    def dashboard(self) -> list[dict]:
        return self.request("GET", f"{API}/me/dashboard")

    def notifications(self, unread_only: bool = False) -> dict:
        return self.request("GET", f"{API}/me/notifications", params={"unread_only": unread_only})

    def read_all_notifications(self) -> None:
        self.request("POST", f"{API}/me/notifications/read-all")

    def export(self) -> dict:
        return self.request("GET", f"{API}/me/export")

    def delete_account(self, password: str) -> None:
        self.request("DELETE", f"{API}/me", json={"password": password, "confirm": "EXCLUIR"})

    # ---------------------------------------------------------------- paciente
    def sync(self, patient_id: str, cursor: int, changes: dict) -> dict:
        return self.request("POST", f"{API}/patients/{patient_id}/sync", json={"cursor": cursor, "changes": changes})

    def care_team(self, patient_id: str) -> dict:
        return self.request("GET", f"{API}/patients/{patient_id}/care-team")

    def create_invite(self, patient_id: str, role: str, can_edit: bool) -> dict:
        return self.request("POST", f"{API}/patients/{patient_id}/invites", json={"role": role, "can_edit": can_edit})

    def revoke_invite(self, patient_id: str, code: str) -> None:
        self.request("DELETE", f"{API}/patients/{patient_id}/invites/{code}")

    def accept_invite(self, code: str) -> dict:
        return self.request("POST", f"{API}/invites/accept", json={"code": code})

    def update_member(self, patient_id: str, member_id: int, **changes) -> dict:
        return self.request("PATCH", f"{API}/patients/{patient_id}/care-team/{member_id}", json=changes)

    def remove_member(self, patient_id: str, member_id: int) -> None:
        self.request("DELETE", f"{API}/patients/{patient_id}/care-team/{member_id}")

    def report_html(self, patient_id: str, days: int = 30) -> str:
        return self.request("GET", f"{API}/patients/{patient_id}/reports/summary.html", params={"days": days})

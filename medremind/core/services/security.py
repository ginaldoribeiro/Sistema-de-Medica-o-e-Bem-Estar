"""Bloqueio por PIN.

O PIN nunca é salvo em texto: guardamos sal + PBKDF2-HMAC-SHA256. Após
tentativas erradas seguidas, o acesso é bloqueado por um tempo crescente.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from ..repositories import SettingsRepository
from .audit import AuditService

ITERATIONS = 200_000
MAX_ATTEMPTS = 5


@dataclass
class UnlockResult:
    ok: bool
    message: str = ""
    locked_until: datetime | None = None


class SecurityService:
    def __init__(self, settings: SettingsRepository, audit: AuditService,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.settings = settings
        self.audit = audit
        self.clock = clock

    @staticmethod
    def _hash(pin: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, ITERATIONS).hex()

    @staticmethod
    def valid_format(pin: str) -> bool:
        return pin.isdigit() and 4 <= len(pin) <= 6

    @property
    def has_pin(self) -> bool:
        return self.settings.get("pin") is not None

    @classmethod
    def check_strength(cls, pin: str) -> None:
        """Lança ValueError com mensagem para o usuário se o PIN for inválido ou óbvio."""
        if not cls.valid_format(pin):
            raise ValueError("O PIN deve ter de 4 a 6 números.")
        if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
            raise ValueError("Escolha um PIN menos previsível (evite 1111 ou 1234).")

    def set_pin(self, pin: str) -> None:
        self.check_strength(pin)
        salt = secrets.token_bytes(16)
        self.settings.set("pin", {"salt": salt.hex(), "hash": self._hash(pin, salt)})
        self.settings.set("pin_attempts", {"count": 0, "locked_until": None})
        self.audit.log("pin_definido")

    def remove_pin(self, current_pin: str) -> bool:
        if not self.verify(current_pin).ok:
            return False
        self.settings.delete("pin")
        self.audit.log("pin_removido")
        return True

    def verify(self, pin: str) -> UnlockResult:
        stored = self.settings.get("pin")
        if stored is None:
            return UnlockResult(True)
        now = self.clock()
        state = self.settings.get("pin_attempts", {"count": 0, "locked_until": None})
        locked_until = datetime.fromisoformat(state["locked_until"]) if state.get("locked_until") else None
        if locked_until and now < locked_until:
            secs = int((locked_until - now).total_seconds()) + 1
            return UnlockResult(False, f"Muitas tentativas. Tente de novo em {secs} s.", locked_until)

        ok = hmac.compare_digest(self._hash(pin, bytes.fromhex(stored["salt"])), stored["hash"])
        if ok:
            self.settings.set("pin_attempts", {"count": 0, "locked_until": None})
            self.audit.log("login_ok", "PIN")
            return UnlockResult(True)

        count = state.get("count", 0) + 1
        new_lock = None
        if count >= MAX_ATTEMPTS:
            # 30 s, 60 s, 120 s ... até 15 min
            new_lock = now + timedelta(seconds=min(900, 30 * 2 ** (count - MAX_ATTEMPTS)))
        self.settings.set("pin_attempts", {"count": count,
                                           "locked_until": new_lock.isoformat() if new_lock else None})
        self.audit.log("login_falhou", f"tentativa {count}")
        left = MAX_ATTEMPTS - count
        msg = "PIN incorreto." + (f" Restam {left} tentativas." if left > 0 else " Acesso bloqueado temporariamente.")
        return UnlockResult(False, msg, new_lock)

"""Senhas (scrypt), tokens de acesso (JWT) e tokens de renovação com rotação."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import Settings
from .orm import RefreshToken, User, new_uuid, utcnow

# scrypt: N=2^15, r=8, p=1 (~32 MB de memória por cálculo)
_N, _R, _P = 2 ** 15, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(),
                                          base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if password.isdigit() or password.isalpha():
        return "Use letras e números na senha."
    return None


# --------------------------------------------------------------------------- JWT
def create_access_token(settings: Settings, user: User) -> str:
    now = utcnow()
    payload = {"sub": user.uuid, "iat": now, "exp": now + timedelta(minutes=settings.access_minutes), "typ": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return payload.get("sub") if payload.get("typ") == "access" else None


# ---------------------------------------------------------------- refresh tokens
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(db: Session, settings: Settings, user: User, user_agent: str = "",
                        family: str | None = None) -> str:
    token = secrets.token_urlsafe(48)
    db.add(RefreshToken(user_id=user.id, token_hash=_hash(token), family=family or new_uuid(),
                        expires_at=utcnow() + timedelta(days=settings.refresh_days), user_agent=user_agent[:200]))
    return token


def rotate_refresh_token(db: Session, settings: Settings, token: str, user_agent: str = "") -> tuple[User, str] | None:
    """Troca um refresh token por outro. Reuso de token já trocado = possível roubo: revoga a família."""
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash(token)))
    if row is None:
        return None
    if row.revoked:
        db.execute(update(RefreshToken).where(RefreshToken.family == row.family).values(revoked=True))
        return None
    if row.expires_at < utcnow():
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    row.revoked = True
    return user, issue_refresh_token(db, settings, user, user_agent, family=row.family)


def revoke_refresh_token(db: Session, token: str) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.token_hash == _hash(token)).values(revoked=True))


def revoke_all(db: Session, user_id: int) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=True))


def invite_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I para ditar por telefone
    return "".join(secrets.choice(alphabet) for _ in range(8))


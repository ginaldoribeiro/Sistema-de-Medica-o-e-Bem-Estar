"""Configuração por variáveis de ambiente (12-factor)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "sim")


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("MEDREMIND_ENV", "development"))
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./medremind-server.db"))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", ""))
    access_minutes: int = field(default_factory=lambda: int(os.environ.get("ACCESS_TOKEN_MINUTES", "15")))
    refresh_days: int = field(default_factory=lambda: int(os.environ.get("REFRESH_TOKEN_DAYS", "30")))
    cors_origins: list[str] = field(default_factory=lambda: [o.strip() for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:8550,http://127.0.0.1:8550").split(",") if o.strip()])
    scheduler_enabled: bool = field(default_factory=lambda: _bool("SCHEDULER_ENABLED", True))
    scheduler_interval_s: int = field(default_factory=lambda: int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "300")))
    default_timezone: str = field(default_factory=lambda: os.environ.get("DEFAULT_TIMEZONE", "America/Sao_Paulo"))
    invite_days: int = 7
    fcm_server_key: str = field(default_factory=lambda: os.environ.get("FCM_SERVER_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    max_sync_items: int = 2000
    redis_url: str = field(default_factory=lambda: os.environ.get("REDIS_URL", ""))

    def __post_init__(self) -> None:
        if not self.jwt_secret:
            if self.env == "production":
                raise RuntimeError("Defina JWT_SECRET em produção.")
            # Em desenvolvimento geramos um segredo efêmero (tokens caem a cada reinício).
            self.jwt_secret = secrets.token_urlsafe(48)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

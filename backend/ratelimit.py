"""Limite de tentativas (janela deslizante).

* ``RateLimiter``: em memória — basta para uma instância.
* ``RedisRateLimiter``: compartilhado entre réplicas da API (defina ``REDIS_URL``).

Os dois têm a mesma interface: ``hit(chave) -> bool`` e ``reset(chave)``.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_s: int) -> None:
        self.limit = limit
        self.window = window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Registra uma tentativa. Devolve False se passou do limite."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


class RedisRateLimiter:
    """Janela deslizante num sorted set do Redis (atômico com MULTI/EXEC)."""

    def __init__(self, url: str, limit: int, window_s: int, prefix: str = "medremind:rl:") -> None:
        import redis

        self.r = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        self.limit = limit
        self.window = window_s
        self.prefix = prefix

    def hit(self, key: str) -> bool:
        import uuid

        k = self.prefix + key
        now = time.time()
        pipe = self.r.pipeline(transaction=True)
        pipe.zremrangebyscore(k, 0, now - self.window)
        pipe.zcard(k)
        pipe.zadd(k, {uuid.uuid4().hex: now})
        pipe.expire(k, self.window)
        _, count, _, _ = pipe.execute()
        if count >= self.limit:
            # Não conta a tentativa bloqueada (senão a janela nunca esvazia sob ataque contínuo).
            self.r.zremrangebyscore(k, now, now)
            return False
        return True

    def reset(self, key: str) -> None:
        self.r.delete(self.prefix + key)


def make_limiter(redis_url: str, limit: int, window_s: int):
    """Usa Redis quando configurado e acessível; senão cai para memória (com aviso no log)."""
    if redis_url:
        try:
            limiter = RedisRateLimiter(redis_url, limit, window_s)
            limiter.r.ping()
            return limiter
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("medremind.api").warning("Redis indisponível em %s; limite em memória", redis_url)
    return RateLimiter(limit, window_s)

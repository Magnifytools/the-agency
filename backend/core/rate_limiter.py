"""Rate limiters with Redis backend (fallback to in-memory).

When REDIS_URL is configured, counters are shared across workers.
If Redis is unavailable, the limiter degrades to local in-memory mode.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Callable

from fastapi import HTTPException, status

from backend.config import settings

try:
    import redis
except Exception:  # pragma: no cover - optional dependency
    redis = None


logger = logging.getLogger(__name__)


def _build_redis_client() -> "redis.Redis | None":
    if not settings.REDIS_URL:
        return None
    if redis is None:
        logger.warning("REDIS_URL configured but redis package is not installed; using in-memory rate limiter")
        return None
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        client.ping()
        logger.info("Rate limiter using Redis backend")
        return client
    except Exception as exc:  # pragma: no cover - depends on runtime infra
        logger.warning("Redis unavailable for rate limiter (%s); using in-memory fallback", exc)
        return None


class _SlidingWindowLimiter:
    def __init__(self, prefix: str, detail_fn: Callable[[int, int], str]) -> None:
        self._prefix = prefix
        self._detail_fn = detail_fn
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._redis = _build_redis_client()

    def _raise_limit(self, max_requests: int, window_seconds: int) -> None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=self._detail_fn(max_requests, window_seconds),
        )

    def _check_memory(self, key: str, max_requests: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]
        if len(self._requests[key]) >= max_requests:
            self._raise_limit(max_requests, window_seconds)
        self._requests[key].append(now)

    def _check_redis(self, key: str, max_requests: int, window_seconds: int) -> None:
        if self._redis is None:
            raise RuntimeError("redis not configured")

        now = time.time()
        cutoff = now - window_seconds
        redis_key = f"{self._prefix}:{key}"

        # Prune old entries and read current size.
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if int(current_count) >= max_requests:
            self._raise_limit(max_requests, window_seconds)

        # Append current request and keep key ttl bounded to window.
        member = f"{now}:{uuid.uuid4().hex}"
        pipe = self._redis.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, window_seconds + 10)
        pipe.execute()

    def check(self, key: str | int, max_requests: int, window_seconds: int) -> None:
        normalized = str(key)
        if self._redis is not None:
            try:
                self._check_redis(normalized, max_requests, window_seconds)
                return
            except HTTPException:
                raise
            except Exception as exc:  # pragma: no cover - depends on runtime infra
                logger.warning("Redis limiter fallback to memory (%s): %s", self._prefix, exc)
                self._redis = None
        self._check_memory(normalized, max_requests, window_seconds)


class RateLimiter:
    """Sliding-window limiter for AI endpoints."""

    def __init__(self) -> None:
        self._limiter = _SlidingWindowLimiter(
            prefix="rate:ai",
            detail_fn=lambda max_requests, window_seconds: (
                "Demasiadas solicitudes de IA. "
                f"Límite: {max_requests} por {window_seconds // 60} minuto(s). "
                "Intenta de nuevo en unos segundos."
            ),
        )

    def check(self, user_id: int, max_requests: int, window_seconds: int) -> None:
        self._limiter.check(user_id, max_requests, window_seconds)


class LoginRateLimiter:
    """Sliding-window limiter for login attempts keyed by email/IP."""

    def __init__(self) -> None:
        self._limiter = _SlidingWindowLimiter(
            prefix="rate:login",
            detail_fn=lambda _max_requests, _window_seconds: "Demasiados intentos de login. Intenta de nuevo en unos minutos.",
        )

    def check(self, key: str, max_requests: int, window_seconds: int) -> None:
        self._limiter.check(key, max_requests, window_seconds)


ai_limiter = RateLimiter()
login_limiter = LoginRateLimiter()

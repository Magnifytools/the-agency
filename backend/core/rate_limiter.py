"""Simple in-memory rate limiter for AI endpoints.

Uses a per-user sliding window to prevent abuse of expensive Claude API calls.
No external dependency required — suitable for a single-process deployment.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, status


class RateLimiter:
    """Sliding-window rate limiter keyed by user id."""

    def __init__(self) -> None:
        self._requests: dict[int, list[float]] = defaultdict(list)

    def check(self, user_id: int, max_requests: int, window_seconds: int) -> None:
        """Raise 429 if *user_id* exceeded *max_requests* in the last *window_seconds*."""
        now = time.monotonic()

        # Prune expired entries
        cutoff = now - window_seconds
        self._requests[user_id] = [t for t in self._requests[user_id] if t > cutoff]

        if len(self._requests[user_id]) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Demasiadas solicitudes de IA. "
                    f"Límite: {max_requests} por {window_seconds // 60} minuto(s). "
                    f"Intenta de nuevo en unos segundos."
                ),
            )

        self._requests[user_id].append(now)


# Singleton shared across all endpoints
ai_limiter = RateLimiter()


class LoginRateLimiter:
    """Sliding-window rate limiter keyed by string (email/IP) for login attempts."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, max_requests: int, window_seconds: int) -> None:
        """Raise 429 if *key* exceeded *max_requests* in the last *window_seconds*."""
        now = time.monotonic()
        cutoff = now - window_seconds
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

        if len(self._requests[key]) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos de login. Intenta de nuevo en unos minutos.",
            )

        self._requests[key].append(now)


login_limiter = LoginRateLimiter()

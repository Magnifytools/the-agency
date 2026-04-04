"""JWT token blacklist with optional Redis persistence.

When REDIS_URL is configured, revoked tokens are shared across workers
and survive restarts. Falls back to in-memory-only otherwise.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict

logger = logging.getLogger(__name__)

# Try to reuse the shared Redis client from rate_limiter
_redis_client = None

def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        from backend.core.rate_limiter import _shared_redis
        _redis_client = _shared_redis
        return _redis_client
    except Exception:
        return None

REDIS_PREFIX = "agency:token_blacklist:"


class TokenBlacklist:
    """Thread-safe token blacklist. Uses Redis when available, in-memory fallback."""

    MAX_SIZE = 10_000

    def __init__(self) -> None:
        self._blacklisted: Dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, jti: str, exp: float) -> None:
        """Blacklist a token by its JTI. `exp` is the Unix expiration timestamp."""
        # Try Redis first
        r = _get_redis()
        if r is not None:
            try:
                ttl = max(int(exp - time.time()), 1)
                r.setex(f"{REDIS_PREFIX}{jti}", ttl, "1")
                return
            except Exception as e:
                logger.warning("Redis blacklist add failed, falling back to memory: %s", e)

        # In-memory fallback
        with self._lock:
            self._cleanup_expired()
            if len(self._blacklisted) < self.MAX_SIZE:
                self._blacklisted[jti] = exp

    def is_blacklisted(self, jti: str) -> bool:
        """Check if a JTI has been blacklisted."""
        # Check Redis first
        r = _get_redis()
        if r is not None:
            try:
                if r.exists(f"{REDIS_PREFIX}{jti}"):
                    return True
            except Exception as e:
                logger.warning("Redis blacklist check failed: %s", e)

        # Check in-memory fallback
        with self._lock:
            if jti not in self._blacklisted:
                return False
            if self._blacklisted[jti] < time.time():
                del self._blacklisted[jti]
                return False
            return True

    def _cleanup_expired(self) -> None:
        """Remove entries whose tokens have naturally expired."""
        now = time.time()
        expired = [jti for jti, exp in self._blacklisted.items() if exp < now]
        for jti in expired:
            del self._blacklisted[jti]

    def clear(self) -> None:
        """Clear all entries. Useful for testing."""
        with self._lock:
            self._blacklisted.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._blacklisted)


# Module-level singleton
token_blacklist = TokenBlacklist()

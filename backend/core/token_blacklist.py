"""In-memory JWT token blacklist for single-instance deployments.

Tokens are stored by JTI (JWT ID) with their expiration time.
Expired entries are lazily cleaned up on each check to bound memory usage.
"""

from __future__ import annotations

import threading
import time
from typing import Dict


class TokenBlacklist:
    """Thread-safe in-memory token blacklist with automatic expiry cleanup."""

    MAX_SIZE = 10_000  # Safety cap — well beyond realistic usage

    def __init__(self) -> None:
        self._blacklisted: Dict[str, float] = {}  # jti -> exp_timestamp
        self._lock = threading.Lock()

    def add(self, jti: str, exp: float) -> None:
        """Blacklist a token by its JTI. `exp` is the token's Unix expiration timestamp."""
        with self._lock:
            self._cleanup_expired()
            if len(self._blacklisted) < self.MAX_SIZE:
                self._blacklisted[jti] = exp

    def is_blacklisted(self, jti: str) -> bool:
        """Check if a JTI has been blacklisted. Also cleans expired entries."""
        with self._lock:
            if jti not in self._blacklisted:
                return False
            # If the entry itself has expired, remove it and return False
            if self._blacklisted[jti] < time.time():
                del self._blacklisted[jti]
                return False
            return True

    def _cleanup_expired(self) -> None:
        """Remove entries whose tokens have naturally expired. Called under lock."""
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

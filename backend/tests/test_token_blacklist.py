import time

import pytest

from backend.core.token_blacklist import TokenBlacklist
from backend.core.security import create_access_token, decode_access_token


class TestTokenBlacklist:
    def setup_method(self):
        self.bl = TokenBlacklist()

    def test_not_blacklisted_by_default(self):
        assert not self.bl.is_blacklisted("some-jti")

    def test_add_and_check(self):
        future_exp = time.time() + 3600
        self.bl.add("jti-1", future_exp)
        assert self.bl.is_blacklisted("jti-1")
        assert not self.bl.is_blacklisted("jti-2")

    def test_expired_entry_is_removed_on_check(self):
        past_exp = time.time() - 1
        self.bl.add("expired-jti", past_exp)
        assert not self.bl.is_blacklisted("expired-jti")
        assert len(self.bl) == 0

    def test_cleanup_removes_expired(self):
        self.bl.add("old", time.time() - 10)
        self.bl.add("valid", time.time() + 3600)
        # Adding another entry triggers cleanup
        self.bl.add("new", time.time() + 3600)
        assert not self.bl.is_blacklisted("old")
        assert self.bl.is_blacklisted("valid")
        assert self.bl.is_blacklisted("new")

    def test_clear(self):
        self.bl.add("jti-1", time.time() + 3600)
        self.bl.clear()
        assert len(self.bl) == 0
        assert not self.bl.is_blacklisted("jti-1")

    def test_max_size_guard(self):
        self.bl.MAX_SIZE = 5
        for i in range(10):
            self.bl.add(f"jti-{i}", time.time() + 3600)
        assert len(self.bl) <= 5


class TestTokenHasJti:
    def test_created_token_contains_jti(self):
        token = create_access_token({"sub": "1"})
        payload = decode_access_token(token)
        assert payload is not None
        assert "jti" in payload
        assert len(payload["jti"]) == 32  # uuid4 hex

    def test_different_tokens_have_different_jti(self):
        t1 = create_access_token({"sub": "1"})
        t2 = create_access_token({"sub": "1"})
        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)
        assert p1["jti"] != p2["jti"]

"""Token del enlace del cliente: aleatorio, sólo se guarda su SHA-256."""
import hashlib
from datetime import date

import pytest

from backend.services import client_share_links as links


def test_new_tokens_are_random_and_match_the_accepted_format():
    tokens = {links.new_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(links._TOKEN_RE.fullmatch(t) for t in tokens)


def test_hash_is_sha256_hex_and_never_the_token():
    token = links.new_token()
    digest = links.hash_token(token)
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert len(digest) == 64 and token not in digest


@pytest.mark.parametrize("token", ["", "corto", "x" * 44, "a" * 42 + "!", "../" + "a" * 40, "á" * 43])
async def test_malformed_tokens_never_reach_the_database(token):
    class Boom:
        async def scalar(self, *_a, **_k):
            raise AssertionError("no debería consultar")
    assert await links.resolve_token(Boom(), token) is None


@pytest.mark.parametrize("day, back, expected", [
    (date(2026, 9, 30), 0, date(2026, 9, 1)),
    (date(2026, 9, 30), 15, date(2025, 6, 1)),
    (date(2026, 1, 15), 1, date(2025, 12, 1)),
])
def test_month_start(day, back, expected):
    assert links._month_start(day, back) == expected

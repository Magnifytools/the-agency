"""revoke_token: revoca en Google y nunca tumba la desconexión local."""

from __future__ import annotations

import httpx
import pytest

from backend.core.security import encrypt_vault_secret
from backend.services import google_oauth


def _transport(handler):
    """httpx.AsyncClient de verdad, pero con un transporte simulado."""
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    return factory


async def test_revoca_con_el_token_en_formulario(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["type"] = request.headers["content-type"]
        return httpx.Response(200)

    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", _transport(handler))

    assert await google_oauth.revoke_token("1//refresh-token") is True
    assert seen["url"] == "https://oauth2.googleapis.com/revoke"
    assert seen["body"] == "token=1%2F%2Frefresh-token"
    assert seen["type"] == "application/x-www-form-urlencoded"


async def test_google_rechaza_el_token_no_lanza(monkeypatch, caplog):
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_token"})

    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", _transport(handler))

    assert await google_oauth.revoke_token("secreto-que-no-se-registra") is False
    assert "HTTP 400" in caplog.text
    assert "secreto-que-no-se-registra" not in caplog.text


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("lento"), httpx.ConnectError("caído"), RuntimeError("raro")])
async def test_error_de_red_no_lanza(monkeypatch, error):
    def handler(request):
        raise error

    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", _transport(handler))

    assert await google_oauth.revoke_token("tok") is False


async def test_sin_token_no_llama_a_google(monkeypatch):
    def handler(request):
        raise AssertionError("no debe llamar a Google")

    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", _transport(handler))

    assert await google_oauth.revoke_token(None) is False
    assert await google_oauth.revoke_token("") is False


def test_timeout_corto():
    assert google_oauth.REVOKE_TIMEOUT_SECONDS == 10


def test_plain_refresh_token_descifra_o_acepta_el_antiguo_en_claro():
    assert google_oauth.plain_refresh_token(encrypt_vault_secret("abc")) == "abc"
    assert google_oauth.plain_refresh_token("legacy-plain") == "legacy-plain"
    assert google_oauth.plain_refresh_token("v1:no-es-fernet") is None
    assert google_oauth.plain_refresh_token(None) is None

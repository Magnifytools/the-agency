"""Sesión deslizante: usar la app la mantiene abierta; dejarla, no."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.core.auth_cookies import renewed_token
from backend.core.security import decode_access_token
from backend.db.database import get_db
from backend.main import app
from backend.tests.conftest import _make_admin, _make_mock_db

LIFE = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def _token(remaining: timedelta) -> str:
    exp = datetime.now(timezone.utc) + remaining
    return jwt.encode({"sub": "1", "exp": exp, "jti": uuid.uuid4().hex}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@pytest.fixture
async def real_auth_client():
    db = _make_mock_db()
    result = MagicMock()
    result.scalar_one_or_none.return_value = _make_admin()
    db.execute.return_value = result
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _set_cookie_names(res) -> dict[str, str]:
    return {h.split("=", 1)[0]: h for h in res.headers.get_list("set-cookie")}


def test_renueva_solo_pasada_la_mitad_de_la_vida():
    assert renewed_token({"sub": "1", "exp": (datetime.now(timezone.utc) + LIFE * 0.9).timestamp()}) is None
    fresh = renewed_token({"sub": "1", "exp": (datetime.now(timezone.utc) + LIFE * 0.3).timestamp()})
    payload = decode_access_token(fresh)
    assert payload["sub"] == "1"
    assert payload["exp"] - datetime.now(timezone.utc).timestamp() > LIFE.total_seconds() * 0.9


async def test_una_cookie_a_media_vida_sale_renovada_con_el_mismo_csrf(real_auth_client):
    old = _token(LIFE * 0.2)
    real_auth_client.cookies.set(settings.AUTH_COOKIE_NAME, old)
    real_auth_client.cookies.set(settings.CSRF_COOKIE_NAME, "csrf-actual")

    res = await real_auth_client.get("/api/auth/me")

    assert res.status_code == 200
    cookies = _set_cookie_names(res)
    assert settings.AUTH_COOKIE_NAME in cookies
    assert f"{settings.CSRF_COOKIE_NAME}=csrf-actual" in cookies[settings.CSRF_COOKIE_NAME]
    assert "HttpOnly" in cookies[settings.AUTH_COOKIE_NAME]


async def test_una_cookie_reciente_no_se_toca(real_auth_client):
    real_auth_client.cookies.set(settings.AUTH_COOKIE_NAME, _token(LIFE * 0.95))
    res = await real_auth_client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.headers.get_list("set-cookie") == []


async def test_el_bearer_de_la_extension_no_se_renueva(real_auth_client):
    res = await real_auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {_token(LIFE * 0.1)}"})
    assert res.status_code == 200
    assert res.headers.get_list("set-cookie") == []


async def test_una_cookie_caducada_no_resucita(real_auth_client):
    real_auth_client.cookies.set(settings.AUTH_COOKIE_NAME, _token(-timedelta(minutes=1)))
    res = await real_auth_client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.headers.get_list("set-cookie") == []


async def test_logout_no_renueva_la_sesion_que_cierra(real_auth_client):
    real_auth_client.cookies.set(settings.AUTH_COOKIE_NAME, _token(LIFE * 0.1))
    real_auth_client.cookies.set(settings.CSRF_COOKIE_NAME, "c")
    res = await real_auth_client.post("/api/auth/logout")
    assert res.status_code == 204
    # Sólo borrados (max-age=0 / expires pasado), ningún token nuevo.
    for header in res.headers.get_list("set-cookie"):
        assert 'Max-Age=0' in header or '=""' in header

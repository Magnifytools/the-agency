"""Bing Webmaster en vivo (`services/bing_live.py` + `api/routes/client_bing.py`): sin BD ni red."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.deps import get_current_user
from backend.api.routes import client_bing
from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.db.database import get_db
from backend.db.models import ClientBingConnection, User, UserRole
from backend.main import app
from backend.services import bing_live

KEY = "c0ffee0123456789abcdef0123456789"
SITE = "https://www.fitgeneration.es/"
HOME = "https://www.fitgeneration.es/"
BLOG = "https://www.fitgeneration.es/blog/"
TODAY = date(2026, 11, 11)


def _ms(day: str) -> str:
    moment = datetime.fromisoformat(day).replace(tzinfo=UTC)
    return f"/Date({int(moment.timestamp() * 1000)})/"


def _bing(routes: dict, seen: list | None = None):
    """MockTransport: `routes[método]` es un dict de respuesta o una función de los parámetros."""

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        params = dict(request.url.params)
        if seen is not None:
            seen.append((method, params))
        if params.get("apikey") != KEY:
            return httpx.Response(400, json={"ErrorCode": 3, "Message": "ERROR!!! InvalidApiKey"})
        answer = routes[method]
        answer = answer(params) if callable(answer) else answer
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json={"d": answer})

    return lambda: httpx.MockTransport(handler)


def _client(website="https://www.fitgeneration.es", gsc_url="sc-domain:fitgeneration.es"):
    return SimpleNamespace(id=7, website=website, gsc_url=gsc_url)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _db(*, connection=None, watches=()):
    db = MagicMock()
    db.get = AsyncMock(side_effect=lambda model, _id: connection if model is ClientBingConnection else None)
    db.execute = AsyncMock(return_value=_Result([SimpleNamespace(url=u, label=lbl) for u, lbl in watches]))
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _connection(status="ok"):
    return ClientBingConnection(client_id=7, api_key=encrypt_vault_secret(KEY), site_url=SITE,
                                status=status, last_error=None, connected_by=None,
                                connected_at=datetime(2026, 11, 11, tzinfo=UTC))


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(bing_live, "business_today", lambda: TODAY)


# ── Lectura de lo que devuelve Bing ──────────────────────────────────


def test_fechas_de_bing():
    assert bing_live.parse_date("/Date(1731283200000)/") == datetime(2024, 11, 11, tzinfo=UTC)
    assert bing_live.parse_date("/Date(1731283200000-0800)/") == datetime(2024, 11, 11, tzinfo=UTC)
    # DateTime.MinValue de .NET = sin fecha.
    assert bing_live.parse_date("/Date(-62135596800000)/") is None
    assert bing_live.parse_date(None) is None
    assert bing_live.parse_date("2026-11-11") is None


@pytest.mark.parametrize("info, state", [
    ({"LastCrawledDate": _ms("2026-11-01"), "HttpStatus": 200}, "crawled"),
    ({"LastCrawledDate": _ms("2026-11-01"), "HttpStatus": 0}, "crawled"),
    ({"LastCrawledDate": _ms("2026-11-01"), "HttpStatus": 301}, "redirect"),
    ({"LastCrawledDate": _ms("2026-11-01"), "HttpStatus": 404}, "crawl_error"),
    ({"DiscoveryDate": _ms("2026-10-01"), "LastCrawledDate": "/Date(-62135596800000)/"}, "discovered"),
    ({"HttpStatus": 0}, "unknown"),
    (None, "unknown"),
])
def test_estado_de_una_url(info, state):
    assert bing_live.url_state(info)["state"] == state


def test_rendimiento_suma_la_ventana_y_pondera_la_posicion():
    rows = [
        # Fuera de la ventana de 28 días que acaba el 9 nov.
        {"Query": BLOG, "Date": _ms("2026-10-01"), "Impressions": 999, "Clicks": 99, "AvgImpressionPosition": 1},
        {"Query": BLOG, "Date": _ms("2026-10-20"), "Impressions": 100, "Clicks": 5, "AvgImpressionPosition": 4},
        {"Query": "https://fitgeneration.es/blog", "Date": _ms("2026-11-09"), "Impressions": 300, "Clicks": 6,
         "AvgImpressionPosition": 8},
        # Sin posición (-1): cuenta en impresiones, no en la media.
        {"Query": BLOG, "Date": _ms("2026-11-02"), "Impressions": 50, "Clicks": 0, "AvgImpressionPosition": -1},
    ]
    result = bing_live.aggregate(rows, bing_live.page_key)

    assert result == {"fitgeneration.es/blog": {"impressions": 450, "clicks": 11, "position": 7.0}}


def test_sitio_sugerido():
    sites = ["https://blog.fitgeneration.es/", "https://www.fitgeneration.es/", "https://otra.com/"]
    assert bing_live.suggested_site(sites, _client()) == "https://www.fitgeneration.es/"
    assert bing_live.suggested_site(["https://blog.fitgeneration.es/"], _client()) == "https://blog.fitgeneration.es/"
    assert bing_live.suggested_site(["https://otra.com/"], _client()) is None
    assert bing_live.suggested_site(sites, _client(website=None, gsc_url=None)) is None


# ── La clave no se escapa ────────────────────────────────────────────


async def test_clave_no_valida_sin_la_clave_en_el_mensaje(monkeypatch):
    monkeypatch.setattr(bing_live, "_transport", _bing({}))
    with pytest.raises(bing_live.BingError) as exc:
        await bing_live.user_sites("otra-clave-falsa-123")
    assert (exc.value.status, exc.value.code) == (422, "invalid_key")
    assert "otra-clave" not in exc.value.message


def test_el_log_de_httpx_no_lleva_la_clave(caplog):
    url = httpx.URL(bing_live.API_BASE + "GetUrlInfo", params={"apikey": KEY, "siteUrl": SITE})
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info('HTTP Request: %s %s "%s"', "GET", url, "HTTP/1.1 200 OK")
    assert KEY not in caplog.text
    assert "apikey=[redacted]" in caplog.text


async def test_sitios_de_la_cuenta_solo_verificados(monkeypatch):
    monkeypatch.setattr(bing_live, "_transport", _bing({"GetUserSites": [
        {"Url": SITE, "IsVerified": True}, {"Url": "https://pendiente.com/", "IsVerified": False},
    ]}))
    assert await bing_live.user_sites(KEY) == [SITE]


# ── Comprobación ─────────────────────────────────────────────────────


def _routes():
    def url_info(params):
        if params["url"] == HOME:
            return {"Url": HOME, "HttpStatus": 200, "LastCrawledDate": _ms("2026-11-01"),
                    "DiscoveryDate": _ms("2024-01-01")}
        if params["url"] == BLOG:
            return httpx.Response(400, json={"ErrorCode": 11, "Message": "ERROR!!! NotFound"})
        return httpx.Response(400, json={"ErrorCode": 2, "Message": "ERROR!!! UnknownError"})

    return {
        "GetUrlInfo": url_info,
        "GetPageStats": [{"Query": HOME, "Date": _ms("2026-11-08"), "Impressions": 40, "Clicks": 2,
                          "AvgImpressionPosition": 6}],
    }


async def test_comprobacion_con_las_urls_vigiladas(monkeypatch):
    seen: list = []
    monkeypatch.setattr(bing_live, "_transport", _bing(_routes(), seen))
    db = _db(connection=_connection(), watches=[(HOME, "Home"), (BLOG, None), ("https://www.fitgeneration.es/x", None)])

    result = await bing_live.check(db, _client())

    home, blog, broken = result["urls"]
    assert (home["state"], home["days_since_crawl"], home["impressions"], home["position"]) == ("crawled", 10, 40, 6.0)
    assert home["label"] == "Home"
    # Bing no la conoce; sin fila de rendimiento no se inventa un cero.
    assert (blog["state"], blog["impressions"], blog["position"]) == ("unknown", None, None)
    # El fallo de una URL no tumba la comprobación.
    assert broken["state"] == "error" and "UnknownError" in broken["error"]
    assert result["window"] == {"start": "2026-10-12", "end": "2026-11-08"}
    assert result["site_url"] == SITE and result["watched_total"] == 3
    assert {m for m, _ in seen} == {"GetUrlInfo", "GetPageStats"}
    assert all(p["siteUrl"] == SITE for _, p in seen)


async def test_sin_urls_vigiladas_mira_la_web(monkeypatch):
    seen: list = []
    monkeypatch.setattr(bing_live, "_transport", _bing(_routes(), seen))
    result = await bing_live.check(_db(connection=_connection()), _client(website="www.fitgeneration.es/"))

    assert [u["url"] for u in result["urls"]] == ["https://www.fitgeneration.es/"]
    assert result["watched_total"] == 0


async def test_como_mucho_max_urls(monkeypatch):
    monkeypatch.setattr(bing_live, "_transport", _bing(_routes()))
    watches = [(f"https://www.fitgeneration.es/p{i}", None) for i in range(bing_live.MAX_URLS + 5)]
    result = await bing_live.check(_db(connection=_connection(), watches=watches), _client())
    assert len(result["urls"]) == bing_live.MAX_URLS
    assert result["watched_total"] == bing_live.MAX_URLS + 5


async def test_sin_conexion(monkeypatch):
    with pytest.raises(bing_live.BingError) as exc:
        await bing_live.check(_db(), _client())
    assert (exc.value.status, exc.value.code) == (409, "not_connected")


async def test_clave_caducada_marca_la_conexion(monkeypatch):
    connection = _connection()
    connection.api_key = encrypt_vault_secret("clave-que-ya-no-vale")
    monkeypatch.setattr(bing_live, "_transport", _bing(_routes()))
    db = _db(connection=connection, watches=[(HOME, None)])

    with pytest.raises(bing_live.BingError) as exc:
        await bing_live.check(db, _client())

    assert (exc.value.status, exc.value.code) == (409, "invalid_key")
    assert connection.status == "invalid" and connection.last_error


async def test_una_comprobacion_buena_limpia_el_error(monkeypatch):
    connection = _connection(status="invalid")
    connection.last_error = "Bing no acepta la clave"
    monkeypatch.setattr(bing_live, "_transport", _bing(_routes()))
    await bing_live.check(_db(connection=connection, watches=[(HOME, None)]), _client())
    assert (connection.status, connection.last_error) == ("ok", None)


async def test_cuota_agotada(monkeypatch):
    routes = _routes()
    routes["GetPageStats"] = httpx.Response(400, json={"ErrorCode": 4, "Message": "ERROR!!! ThrottleUser"})
    monkeypatch.setattr(bing_live, "_transport", _bing(routes))
    with pytest.raises(bing_live.BingError) as exc:
        await bing_live.check(_db(connection=_connection(), watches=[(HOME, None)]), _client())
    assert (exc.value.status, exc.value.code) == (429, "rate_limited")


async def test_consultas_de_una_url(monkeypatch):
    rows = [
        {"Query": "Gimnasio Madrid", "Date": _ms("2026-11-08"), "Impressions": 30, "Clicks": 1, "AvgImpressionPosition": 5},
        {"Query": "gimnasio madrid", "Date": _ms("2026-11-01"), "Impressions": 10, "Clicks": 0, "AvgImpressionPosition": 9},
        {"Query": "fit generation", "Date": _ms("2026-11-08"), "Impressions": 50, "Clicks": 20, "AvgImpressionPosition": 1},
    ]
    seen: list = []
    monkeypatch.setattr(bing_live, "_transport", _bing({"GetPageQueryStats": rows}, seen))

    result = await bing_live.page_queries(_db(connection=_connection(), watches=[(HOME, None)]), _client(), HOME)

    assert result["queries"] == [
        {"query": "fit generation", "impressions": 50, "clicks": 20, "position": 1.0},
        {"query": "gimnasio madrid", "impressions": 40, "clicks": 1, "position": 6.0},
    ]
    assert seen[0][1]["page"] == HOME


async def test_consultas_solo_de_las_urls_que_se_comprueban():
    with pytest.raises(bing_live.BingError) as exc:
        await bing_live.page_queries(_db(connection=_connection(), watches=[(HOME, None)]), _client(),
                                     "https://otra.com/")
    assert (exc.value.status, exc.value.code) == (422, "unknown_url")


# ── Rutas ────────────────────────────────────────────────────────────


def _user(role=UserRole.member, module="clients"):
    user = MagicMock(spec=User)
    user.id = 9
    user.role = role
    user.permissions = [SimpleNamespace(module=module, can_read=True, can_write=False)] if module else []
    return user


async def _request(user, db, method, path, json=None):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            return await http.request(method, f"/api/clients/7{path}", json=json)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client_found(monkeypatch):
    monkeypatch.setattr(client_bing, "get_client_or_404", AsyncMock(return_value=_client()))


async def test_ruta_comprobar_pide_lectura_de_clientes(client_found):
    response = await _request(_user(module="tasks"), _db(), "POST", "/bing/check")
    assert response.status_code == 403


async def test_ruta_comprobar_devuelve_el_error_de_bing(client_found):
    response = await _request(_user(), _db(), "POST", "/bing/check")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_connected"


async def test_ruta_conexion_nunca_devuelve_la_clave(client_found):
    response = await _request(_user(), _db(connection=_connection()), "GET", "/bing/connection")
    assert response.status_code == 200
    assert response.json()["site_url"] == SITE and response.json()["connected"] is True
    assert KEY not in response.text and "api_key" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("method, path, body", [
    ("POST", "/bing/connection/sites", {"api_key": KEY}),
    ("PUT", "/bing/connection", {"api_key": KEY, "site_url": SITE}),
    ("DELETE", "/bing/connection", None),
])
async def test_gestionar_la_conexion_es_de_admin(client_found, method, path, body):
    response = await _request(_user(), _db(), method, path, json=body)
    assert response.status_code == 403


async def test_conectar_guarda_la_clave_cifrada(client_found, monkeypatch):
    monkeypatch.setattr(bing_live, "_transport", _bing({"GetUserSites": [{"Url": SITE, "IsVerified": True}]}))
    db = _db()

    response = await _request(_user(role=UserRole.admin), db, "PUT", "/bing/connection",
                              json={"api_key": f"  {KEY} ", "site_url": SITE})

    assert response.status_code == 200, response.text
    saved = db.add.call_args.args[0]
    assert saved.api_key.startswith("v1:") and decrypt_vault_secret(saved.api_key) == KEY
    assert (saved.site_url, saved.status, saved.connected_by) == (SITE, "ok", 9)
    assert KEY not in response.text


async def test_conectar_un_sitio_que_la_cuenta_no_ve(client_found, monkeypatch):
    monkeypatch.setattr(bing_live, "_transport", _bing({"GetUserSites": [{"Url": SITE, "IsVerified": True}]}))
    db = _db()
    response = await _request(_user(role=UserRole.admin), db, "PUT", "/bing/connection",
                              json={"api_key": KEY, "site_url": "https://otra.com/"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_site"
    db.add.assert_not_called()


async def test_sitios_de_una_clave_con_el_sugerido(client_found, monkeypatch):
    monkeypatch.setattr(bing_live, "_transport", _bing({"GetUserSites": [
        {"Url": "https://otra.com/", "IsVerified": True}, {"Url": SITE, "IsVerified": True}]}))
    response = await _request(_user(role=UserRole.admin), _db(), "POST", "/bing/connection/sites",
                              json={"api_key": KEY})
    assert response.status_code == 200
    assert response.json() == {"sites": ["https://otra.com/", SITE], "suggested": SITE}


async def test_desconectar_borra_la_fila(client_found):
    connection = _connection()
    db = _db(connection=connection)
    response = await _request(_user(role=UserRole.admin), db, "DELETE", "/bing/connection")
    assert response.status_code == 200 and response.json()["connected"] is False
    db.delete.assert_awaited_once_with(connection)


def test_la_conexion_de_bing_queda_fuera_del_journal():
    """Guarda un secreto: el journal copia columnas a change_logs."""
    from backend.services import change_journal as cj

    assert ClientBingConnection not in cj._SPECS

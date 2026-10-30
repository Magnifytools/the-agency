"""Search Console en vivo (`services/gsc_live.py` + `api/routes/client_gsc.py`): sin BD ni red."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError
from httpx import ASGITransport, AsyncClient

from backend.api.deps import get_current_user
from backend.api.routes import client_gsc
from backend.db.database import get_db
from backend.db.models import User, UserRole
from backend.main import app
from backend.services import gsc_live, gsc_service
from backend.services.gsc_service import GscAuthError, GscSiteError

TODAY = date(2026, 10, 28)
SITE = "sc-domain:cigarraldecaravantes.com"
PAGE = "https://cigarraldecaravantes.com/restaurante/"


class _FakeService:
    """Imita `searchanalytics().query(...).execute()`: responde según el cuerpo y lo apunta."""

    def __init__(self, *, rows=None, totals=None, latest=("2026-10-25", "2026-10-24"), error=None):
        self.rows = rows if rows is not None else []
        self.totals = totals
        self.latest = latest
        self.error = error
        self.calls: list[tuple[str, dict, int | None]] = []
        self._pending: tuple[str, dict] | None = None

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):  # noqa: N803 — nombre de la API de Google
        self._pending = (siteUrl, dict(body))
        return self

    def execute(self, num_retries=None):
        site, body = self._pending
        self.calls.append((site, body, num_retries))
        if self.error is not None:
            raise self.error
        if body.get("dimensions") == ["date"] and body.get("rowLimit") == gsc_live.LATEST_LOOKBACK_DAYS + 1:
            return {"rows": [{"keys": [d], "clicks": 1, "impressions": 1} for d in self.latest]}
        if not body.get("dimensions"):
            return {"rows": [self.totals]} if self.totals else {}
        return {"rows": self.rows}

    def body(self, kind: str) -> dict:
        for _, body, _ in self.calls:
            dims = body.get("dimensions")
            is_latest = dims == ["date"] and body.get("rowLimit") == gsc_live.LATEST_LOOKBACK_DAYS + 1
            if kind == "latest" and is_latest:
                return body
            if kind == "totals" and not dims:
                return body
            if kind == "rows" and dims and not is_latest:
                return body
        raise AssertionError(f"no se pidió {kind}")


class _FakeDb:
    def __init__(self, connections):
        self.connections = connections
        self.commits = 0

    async def scalars(self, _stmt):
        return SimpleNamespace(all=lambda: list(self.connections))

    async def commit(self):
        self.commits += 1


def _connection(cid=1, status="connected", email="digital@magnify.ing"):
    return SimpleNamespace(id=cid, refresh_token=f"v1:token-{cid}", google_email=email, status=status)


def _client(gsc_url=SITE):
    return SimpleNamespace(id=28, name="Cigarral de Caravantes", gsc_url=gsc_url)


def _sites(*entries):
    """list_fn falso: token → propiedades que ve esa cuenta."""
    by_token = {}
    for token, site_url, permission in entries:
        by_token.setdefault(token, []).append({"site_url": site_url, "permission": permission})

    async def list_fn(token):
        value = by_token.get(token, [])
        if isinstance(value, Exception):
            raise value
        return value
    return list_fn


@pytest.fixture(autouse=True)
def _clear_sites_cache():
    gsc_live._sites_cache.clear()
    yield
    gsc_live._sites_cache.clear()


@pytest.fixture
def service(monkeypatch):
    def install(fake: _FakeService):
        monkeypatch.setattr(gsc_service, "_service", lambda _token: fake)
        return fake
    return install


def _http_error(status: int, reason: str = "boom") -> HttpError:
    content = ('{"error": {"code": %d, "message": "%s"}}' % (status, reason)).encode()
    return HttpError(httplib2.Response({"status": status}), content)


async def _query(db=None, client=None, list_fn=None, **kwargs):
    params = {"start_date": date(2026, 9, 1), "end_date": date(2026, 9, 30), "dimensions": ["date"]}
    params.update(kwargs)
    return await gsc_live.query(
        db or _FakeDb([_connection()]), client or _client(),
        list_fn=list_fn or _sites(("v1:token-1", SITE, "siteOwner")), today=TODAY, **params,
    )


# ── Consulta ──────────────────────────────────────────────────────────


async def test_filas_por_dia_con_filtro_de_pagina_y_totales_sin_dimensiones(service):
    fake = service(_FakeService(
        rows=[{"keys": ["2026-09-01"], "clicks": 200, "impressions": 4000, "ctr": 0.05, "position": 3.25},
              {"keys": ["2026-09-02"], "clicks": 156, "impressions": 3100, "ctr": 0.0503, "position": 4.1}],
        totals={"clicks": 356, "impressions": 7100, "ctr": 0.0501, "position": 3.6},
    ))
    db = _FakeDb([_connection()])

    result = await _query(db, filters=[{"dimension": "page", "operator": "equals", "expression": PAGE}])

    rows_body, totals_body = fake.body("rows"), fake.body("totals")
    group = [{"groupType": "and", "filters": [{"dimension": "page", "operator": "equals", "expression": PAGE}]}]
    assert rows_body == {"startDate": "2026-09-01", "endDate": "2026-09-30", "type": "web",
                         "aggregationType": "auto", "dataState": "final", "dimensionFilterGroups": group,
                         "dimensions": ["date"], "rowLimit": 1000, "startRow": 0}
    # Mismo filtro, periodo, tipo y agregación, pero sin dimensiones.
    assert "dimensions" not in totals_body
    assert {k: v for k, v in totals_body.items() if k != "rowLimit"} == {
        k: v for k, v in rows_body.items() if k not in ("dimensions", "rowLimit", "startRow")}
    assert all(retries == gsc_live.NUM_RETRIES for _, _, retries in fake.calls)
    assert {site for site, _, _ in fake.calls} == {SITE}
    assert result["rows"][0] == {"keys": {"date": "2026-09-01"}, "clicks": 200, "impressions": 4000,
                                 "ctr": 0.05, "position": 3.25}
    assert sum(r["clicks"] for r in result["rows"]) == 356
    assert result["totals"] == {"clicks": 356, "impressions": 7100, "ctr": 0.0501, "position": 3.6}
    assert result["property"] == SITE
    assert result["data_available_until"] == "2026-10-25"
    assert (result["row_count"], result["has_more"], result["next_start_row"]) == (2, False, None)
    assert db.commits == 1  # la transacción se cierra antes de llamar a Google


async def test_los_totales_salen_de_google_no_de_sumar_filas(service):
    service(_FakeService(
        rows=[{"keys": ["restaurante toledo"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 2.0}],
        totals={"clicks": 356, "impressions": 9000, "ctr": 0.0396, "position": 5.2},
    ))

    result = await _query(dimensions=["query"])

    assert result["rows"][0]["keys"] == {"query": "restaurante toledo"}
    assert result["totals"]["clicks"] == 356


async def test_pagina_con_start_row_y_has_more(service):
    fake = service(_FakeService(rows=[{"keys": [f"q{i}", "ES"], "clicks": 1, "impressions": 2}
                                      for i in range(5)]))

    result = await _query(dimensions=["query", "country"], row_limit=5, start_row=10,
                          search_type="image", aggregation_type="byPage", data_state="all")

    body = fake.body("rows")
    assert (body["rowLimit"], body["startRow"], body["type"]) == (5, 10, "image")
    assert (body["aggregationType"], body["dataState"]) == ("byPage", "all")
    assert fake.body("latest")["dataState"] == "all"
    assert (result["has_more"], result["next_start_row"]) == (True, 15)
    assert result["rows"][0]["keys"] == {"query": "q0", "country": "ES"}
    assert result["rows"][0]["ctr"] is None  # lo que Google no manda no se inventa
    assert result["totals"] == {"clicks": 0, "impressions": 0, "ctr": None, "position": None}


@pytest.mark.parametrize("start, end, code", [
    (date(2026, 9, 30), date(2026, 9, 1), "invalid_dates"),
    (date(2026, 10, 1), date(2026, 10, 29), "invalid_dates"),
    (date(2025, 6, 1), date(2025, 6, 30), "out_of_range"),
])
async def test_fechas_no_validas_son_un_error_claro(service, start, end, code):
    fake = service(_FakeService())

    with pytest.raises(gsc_live.GscLiveError) as exc:
        await _query(start_date=start, end_date=end)

    assert (exc.value.status, exc.value.code) == (422, code)
    assert fake.calls == []


def test_el_limite_es_de_16_meses():
    gsc_live.check_dates(date(2025, 6, 29), date(2025, 7, 1), today=TODAY)
    with pytest.raises(gsc_live.GscLiveError):
        gsc_live.check_dates(date(2025, 6, 28), date(2025, 7, 1), today=TODAY)


@pytest.mark.parametrize("error, status, code", [
    (_http_error(400, "Invalid regex"), 422, "invalid_query"),
    (_http_error(403), 403, "no_access"),
    (_http_error(429), 429, "rate_limited"),
    (_http_error(500), 502, "google_error"),
    (_http_error(401), 409, "reconnect_required"),
])
async def test_errores_de_google_se_traducen(service, error, status, code):
    service(_FakeService(error=error))

    with pytest.raises(gsc_live.GscLiveError) as exc:
        await _query()

    assert (exc.value.status, exc.value.code) == (status, code)
    if code == "invalid_query":
        assert "Invalid regex" in exc.value.message


# ── Propiedades ──────────────────────────────────────────────────────


async def test_propiedades_del_cliente_principal_primero_y_mismo_dominio(service):
    service(_FakeService())
    list_fn = _sites(
        ("v1:token-1", "https://cigarraldecaravantes.com/", "siteRestrictedUser"),
        ("v1:token-1", SITE, "siteFullUser"),
        ("v1:token-1", "https://otrocliente.es/", "siteOwner"),
        ("v1:token-2", "https://cigarraldecaravantes.com/", "siteOwner"),
        ("v1:token-2", "https://blog.cigarraldecaravantes.com/", "siteOwner"),
        ("v1:token-2", "sc-domain:caravantes.com", "siteOwner"),
    )
    db = _FakeDb([_connection(1), _connection(2, email="seo@bisiesto.es")])

    result = await gsc_live.properties(db, _client(), list_fn=list_fn, today=TODAY)

    props = result["properties"]
    assert [p["property"] for p in props] == [
        SITE, "https://blog.cigarraldecaravantes.com/", "https://cigarraldecaravantes.com/"]
    assert props[0] == {"property": SITE, "type": "domain", "is_default": True,
                        "permission_level": "siteFullUser", "data_available_until": "2026-10-25", "error": None}
    # Gana la cuenta con más permiso.
    assert props[2]["permission_level"] == "siteOwner" and props[2]["type"] == "url_prefix"


async def test_propiedad_principal_sin_cuenta_que_la_vea(service):
    fake = service(_FakeService())
    list_fn = _sites(("v1:token-2", "https://otra.es/", "siteOwner"))

    async def broken(token):
        if token == "v1:token-1":
            raise GscAuthError("expired")
        return await list_fn(token)

    db = _FakeDb([_connection(1), _connection(2, email="seo@bisiesto.es")])
    result = await gsc_live.properties(db, _client(), list_fn=broken, today=TODAY)

    assert result["properties"] == [{"property": SITE, "type": "domain", "is_default": True,
                                     "permission_level": None, "data_available_until": None,
                                     "error": "no_access"}]
    assert result["reconnect_required"] == ["digital@magnify.ing"]
    assert fake.calls == []

    with pytest.raises(gsc_live.GscLiveError) as exc:
        await _query(db=_FakeDb([_connection(1), _connection(2)]), list_fn=broken)
    assert exc.value.code == "no_access"
    assert "digital@magnify.ing" in exc.value.message


async def test_property_tiene_que_ser_del_cliente(service):
    fake = service(_FakeService())
    list_fn = _sites(("v1:token-1", SITE, "siteOwner"),
                     ("v1:token-1", "https://cigarraldecaravantes.com/", "siteOwner"),
                     ("v1:token-1", "https://otrocliente.es/", "siteOwner"))

    with pytest.raises(gsc_live.GscLiveError) as exc:
        await _query(list_fn=list_fn, property_url="https://otrocliente.es/")
    assert (exc.value.status, exc.value.code) == (422, "unknown_property")
    assert SITE in exc.value.message
    assert fake.calls == []

    # Sin barra final también vale (como `normalize_site_url`).
    result = await _query(list_fn=list_fn, property_url="https://cigarraldecaravantes.com")
    assert result["property"] == "https://cigarraldecaravantes.com/"


@pytest.mark.parametrize("gsc_url, connections, code", [
    (None, [_connection()], "no_property"),
    (SITE, [], "not_connected"),
    (SITE, [_connection(status="reconnect_required")], "reconnect_required"),
])
async def test_sin_propiedad_o_sin_conexion(service, gsc_url, connections, code):
    service(_FakeService())

    with pytest.raises(gsc_live.GscLiveError) as exc:
        await gsc_live.properties(_FakeDb(connections), _client(gsc_url), list_fn=_sites(), today=TODAY)

    assert (exc.value.status, exc.value.code) == (409, code)


async def test_lo_que_ve_cada_cuenta_se_reutiliza_unos_minutos(service):
    service(_FakeService())
    calls = []
    inner = _sites(("v1:token-1", SITE, "siteOwner"))

    async def list_fn(token):
        calls.append(token)
        return await inner(token)

    await _query(list_fn=list_fn)
    await _query(list_fn=list_fn)

    assert calls == ["v1:token-1"]


def test_una_cuenta_que_no_lista_no_tumba_a_las_demas():
    assert gsc_live._belongs("https://www.x.com/", "x.com")
    assert gsc_live._belongs("sc-domain:shop.x.com", "x.com")
    assert not gsc_live._belongs("https://notx.com/", "x.com")
    assert gsc_live._domain("https://WWW.X.com/blog/") == "x.com"


# ── Ruta ─────────────────────────────────────────────────────────────


@pytest.fixture
def route(monkeypatch):
    """La ruta con el servicio sustituido: devuelve lo que recibió el servicio."""
    seen: dict = {}

    async def fake_query(db, client, **kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(client_gsc, "get_client_or_404", AsyncMock(return_value=_client()))
    monkeypatch.setattr(gsc_live, "query", fake_query)
    return seen


def _user(module=None):
    user = MagicMock(spec=User)
    user.id = 9
    user.role = UserRole.member
    user.permissions = [SimpleNamespace(module=module, can_read=True, can_write=False)] if module else []
    return user


async def _post(user, body):
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            return await http.post("/api/clients/28/gsc/query", json=body)
    finally:
        app.dependency_overrides.clear()


BODY = {"start_date": "2026-09-01", "end_date": "2026-09-30", "dimensions": ["date"],
        "filters": [{"dimension": "page", "operator": "equals", "expression": PAGE}]}


async def test_ruta_pasa_los_parametros_con_sus_valores_por_defecto(route):
    response = await _post(_user("clients"), BODY)

    assert response.status_code == 200, response.text
    assert route["filters"] == [{"dimension": "page", "operator": "equals", "expression": PAGE}]
    assert (route["search_type"], route["aggregation_type"], route["data_state"]) == ("web", "auto", "final")
    assert (route["row_limit"], route["start_row"], route["property_url"]) == (1000, 0, None)
    assert route["start_date"] == date(2026, 9, 1)


async def test_ruta_sin_lectura_de_clientes_es_403(route):
    response = await _post(_user("tasks"), BODY)
    assert response.status_code == 403


@pytest.mark.parametrize("change", [
    {"dimensions": ["date", "query", "page", "country"]},
    {"dimensions": ["query", "query"]},
    {"dimensions": ["hour"]},
    {"filters": [{"dimension": "date", "operator": "equals", "expression": "2026-09-01"}]},
    {"filters": [{"dimension": "page", "operator": "startsWith", "expression": "x"}]},
    {"search_type": "shopping"},
    {"aggregation_type": "byNewsShowcasePanel"},
    {"data_state": "hourly_all"},
    {"row_limit": 25001},
    {"start_row": -1},
    {"start_date": "01/09/2026"},
])
async def test_ruta_rechaza_parametros_no_validos(route, change):
    response = await _post(_user("clients"), {**BODY, **change})
    assert response.status_code == 422
    assert route == {}


async def test_ruta_devuelve_el_error_del_servicio_con_codigo_y_mensaje(route, monkeypatch):
    async def failing(*_args, **_kwargs):
        raise gsc_live.GscLiveError(409, "no_property", "El cliente #28 no tiene propiedad")
    monkeypatch.setattr(gsc_live, "query", failing)

    response = await _post(_user("clients"), BODY)

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "no_property", "message": "El cliente #28 no tiene propiedad"}

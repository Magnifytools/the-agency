"""GA4 en vivo (`services/ga4_live.py` + `api/routes/client_ga4.py`): sin BD ni red."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError
from httpx import ASGITransport, AsyncClient

from backend.api.deps import get_current_user
from backend.api.routes import client_ga4
from backend.db.database import get_db
from backend.db.models import User, UserRole
from backend.main import app
from backend.services import ga4_live
from backend.services.ga4_service import Ga4Error
from backend.services.gsc_service import GscAuthError

TODAY = date(2026, 10, 28)
PROPERTY = "345678901"


def _row(dims, mets):
    return {"dimensionValues": [{"value": d} for d in dims], "metricValues": [{"value": str(m)} for m in mets]}


class _FakeService:
    """Imita `properties().runReport(...).execute()`: responde según el cuerpo y lo apunta."""

    def __init__(self, *, rows=None, totals=None, row_count=None, latest=("20261025", "20261024"), error=None):
        self.rows = rows if rows is not None else []
        self.totals = totals
        self.row_count = row_count
        self.latest = latest
        self.error = error
        self.calls: list[tuple[str, dict, int | None]] = []
        self._pending: tuple[str, dict] | None = None

    def properties(self):
        return self

    def runReport(self, property, body):  # noqa: N802 — nombre de la API de Google
        self._pending = (property, dict(body))
        return self

    def execute(self, num_retries=None):
        prop, body = self._pending
        self.calls.append((prop, body, num_retries))
        if self.error is not None:
            raise self.error
        if "metricAggregations" not in body:  # el del último día
            return {"rows": [_row([d], [1]) for d in self.latest]}
        out = {"rows": self.rows,
               "rowCount": self.row_count if self.row_count is not None else len(self.rows)}
        if self.totals is not None:
            out["totals"] = [_row(["RESERVED_TOTAL"], self.totals)]
        return out

    def body(self, kind: str) -> dict:
        for _, body, _ in self.calls:
            if (kind == "report") == ("metricAggregations" in body):
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


def _client(ga4_property_id=PROPERTY):
    return SimpleNamespace(id=28, name="Cigarral de Caravantes", ga4_property_id=ga4_property_id)


def _visible(**by_token):
    """list_fn falso: token → propiedades que ve esa cuenta (o la excepción que lanza)."""
    async def list_fn(token):
        value = by_token.get(token.replace("v1:", "").replace("-", "_"), [])
        if isinstance(value, Exception):
            raise value
        return value
    return list_fn


@pytest.fixture(autouse=True)
def _clear_cache():
    ga4_live._properties_cache.clear()
    yield
    ga4_live._properties_cache.clear()


@pytest.fixture
def service(monkeypatch):
    def install(fake: _FakeService):
        monkeypatch.setattr(ga4_live, "_data_service", lambda _token: fake)
        return fake
    return install


def _http_error(status: int, reason: str = "boom") -> HttpError:
    content = ('{"error": {"code": %d, "message": "%s"}}' % (status, reason)).encode()
    return HttpError(httplib2.Response({"status": status}), content)


async def _query(db=None, client=None, list_fn=None, **kwargs):
    params = {"start_date": date(2026, 9, 1), "end_date": date(2026, 9, 30),
              "dimensions": ["date"], "metrics": ["sessions"]}
    params.update(kwargs)
    return await ga4_live.query(
        db or _FakeDb([_connection()]), client or _client(),
        list_fn=list_fn or _visible(token_1=[PROPERTY]), today=TODAY, **params,
    )


# ── Consulta ──────────────────────────────────────────────────────────


async def test_sesiones_por_canal_con_totales_del_mismo_informe(service):
    fake = service(_FakeService(
        rows=[_row(["Organic Search"], [812, "0.6231527093596059"]), _row(["Direct"], [240, "0.5"])],
        totals=[1090, "0.6"], row_count=3,
    ))
    db = _FakeDb([_connection()])

    result = await _query(db, dimensions=["sessionDefaultChannelGroup"], metrics=["sessions", "engagementRate"],
                          limit=2)

    body = fake.body("report")
    assert body == {
        "dateRanges": [{"startDate": "2026-09-01", "endDate": "2026-09-30"}],
        "dimensions": [{"name": "sessionDefaultChannelGroup"}],
        "metrics": [{"name": "sessions"}, {"name": "engagementRate"}],
        "metricAggregations": ["TOTAL"], "keepEmptyRows": False, "limit": 2, "offset": 0,
        # Sin orden pedido: por la primera métrica, de mayor a menor.
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    }
    assert {prop for prop, _, _ in fake.calls} == {f"properties/{PROPERTY}"}
    assert all(retries == ga4_live.NUM_RETRIES for _, _, retries in fake.calls)
    assert result["rows"][0] == {"keys": {"sessionDefaultChannelGroup": "Organic Search"},
                                 "metrics": {"sessions": 812, "engagementRate": 0.6231527093596059}}
    # Los totales vienen de GA4 (también hay filas fuera de esta página).
    assert result["totals"] == {"sessions": 1090, "engagementRate": 0.6}
    assert isinstance(result["totals"]["sessions"], int)
    assert (result["row_count"], result["total_rows"], result["has_more"], result["next_offset"]) == (2, 3, True, 2)
    assert result["property_id"] == PROPERTY
    assert result["data_available_until"] == "2026-10-25"
    assert (result["dimensions"], result["metrics"]) == (["sessionDefaultChannelGroup"], ["sessions", "engagementRate"])
    assert db.commits == 1  # la transacción se cierra antes de llamar a Google


async def test_la_fecha_sale_con_guiones_y_ordenada(service):
    fake = service(_FakeService(rows=[_row(["20260901"], [10]), _row(["20260902"], [12])], totals=[22]))

    result = await _query()

    assert fake.body("report")["orderBys"] == [{"dimension": {"dimensionName": "date"}, "desc": False}]
    assert [r["keys"]["date"] for r in result["rows"]] == ["2026-09-01", "2026-09-02"]
    assert (result["has_more"], result["next_offset"]) == (False, None)


async def test_filtros_se_combinan_con_and_y_los_negados_van_en_not_expression(service):
    fake = service(_FakeService())

    await _query(dimensions=["sessionCampaignName"], metrics=["sessions", "keyEvents"], offset=50, filters=[
        {"dimension": "sessionSourceMedium", "operator": "equals", "expression": "google / organic"},
        {"dimension": "sessionCampaignName", "operator": "contains", "expression": "gbp"},
        {"dimension": "landingPage", "operator": "regex", "expression": "/blog/.*"},
        {"dimension": "country", "operator": "notEquals", "expression": "Spain"},
        {"dimension": "pagePath", "operator": "notContains", "expression": "?"},
        {"dimension": "eventName", "operator": "notRegex", "expression": "scroll|click"},
    ], order_by=[{"field": "keyEvents", "desc": True}, {"field": "sessionCampaignName", "desc": False}])

    body = fake.body("report")

    def leaf(dim, match, value):
        return {"filter": {"fieldName": dim, "stringFilter": {"matchType": match, "value": value}}}

    assert body["dimensionFilter"] == {"andGroup": {"expressions": [
        leaf("sessionSourceMedium", "EXACT", "google / organic"),
        leaf("sessionCampaignName", "CONTAINS", "gbp"),
        leaf("landingPage", "FULL_REGEXP", "/blog/.*"),
        {"notExpression": leaf("country", "EXACT", "Spain")},
        {"notExpression": leaf("pagePath", "CONTAINS", "?")},
        {"notExpression": leaf("eventName", "FULL_REGEXP", "scroll|click")},
    ]}}
    assert body["offset"] == 50
    assert body["orderBys"] == [{"metric": {"metricName": "keyEvents"}, "desc": True},
                                {"dimension": {"dimensionName": "sessionCampaignName"}, "desc": False}]


async def test_sin_filas_los_totales_son_cero(service):
    service(_FakeService(rows=[], totals=None, row_count=0))

    result = await _query(metrics=["sessions", "averageSessionDuration"])

    assert result["rows"] == []
    assert result["totals"] == {"sessions": 0, "averageSessionDuration": 0}
    assert (result["row_count"], result["total_rows"], result["has_more"]) == (0, 0, False)


async def test_sin_dimensiones_la_unica_fila_es_el_total(service):
    fake = service(_FakeService(rows=[_row([], [1500, "41.5"])], totals=None))

    result = await _query(dimensions=[], metrics=["sessions", "averageSessionDuration"])

    assert fake.body("report")["dimensions"] == []
    assert result["rows"] == [{"keys": {}, "metrics": {"sessions": 1500, "averageSessionDuration": 41.5}}]
    assert result["totals"] == {"sessions": 1500, "averageSessionDuration": 41.5}


@pytest.mark.parametrize("start, end", [
    (date(2026, 9, 30), date(2026, 9, 1)),
    (date(2026, 10, 1), date(2026, 10, 29)),
])
async def test_fechas_no_validas_son_un_error_claro(service, start, end):
    fake = service(_FakeService())

    with pytest.raises(ga4_live.Ga4LiveError) as exc:
        await _query(start_date=start, end_date=end)

    assert (exc.value.status, exc.value.code) == (422, "invalid_dates")
    assert fake.calls == []


async def test_no_se_limita_a_16_meses(service):
    service(_FakeService())
    # GA4 decide qué guarda cada propiedad: aquí sólo se mira el orden y el futuro.
    result = await _query(start_date=date(2023, 1, 1), end_date=date(2023, 1, 31))
    assert result["start_date"] == "2023-01-01"


@pytest.mark.parametrize("change", [
    {"dimensions": ["date", "country", "city", "eventName", "pagePath", "landingPage"]},
    {"dimensions": ["date", "date"]},
    {"dimensions": ["hour"]},
    {"metrics": []},
    {"metrics": ["sessions", "sessions"]},
    {"metrics": ["bounceRate"]},
    {"filters": [{"dimension": "hour", "operator": "equals", "expression": "1"}]},
    {"filters": [{"dimension": "country", "operator": "startsWith", "expression": "S"}]},
    {"limit": 100001},
    {"offset": -1},
    {"order_by": [{"field": "newUsers", "desc": True}]},
])
async def test_el_servicio_valida_lo_mismo_que_la_ruta(service, change):
    fake = service(_FakeService())

    with pytest.raises(ga4_live.Ga4LiveError) as exc:
        await _query(**change)

    assert (exc.value.status, exc.value.code) == (422, "invalid_query")
    assert fake.calls == []


@pytest.mark.parametrize("error, status, code", [
    (_http_error(400, "Field xyz is not a valid dimension"), 422, "invalid_query"),
    (_http_error(403), 403, "no_access"),
    (_http_error(403, "Request had insufficient authentication scopes."), 403, "missing_scope"),
    (_http_error(429), 429, "rate_limited"),
    (_http_error(500), 502, "google_error"),
    (_http_error(401), 409, "reconnect_required"),
])
async def test_errores_de_google_se_traducen(service, error, status, code):
    service(_FakeService(error=error))

    with pytest.raises(ga4_live.Ga4LiveError) as exc:
        await _query()

    assert (exc.value.status, exc.value.code) == (status, code)
    if code == "invalid_query":
        assert "is not a valid dimension" in exc.value.message
    if code == "missing_scope":
        assert "Ajustes → Search Console" in exc.value.message


# ── Propiedad ────────────────────────────────────────────────────────


async def test_propiedad_la_ve_la_primera_cuenta_que_la_lista(service):
    service(_FakeService())
    list_fn = _visible(token_1=["111111"], token_2=[PROPERTY], token_3=[PROPERTY])
    db = _FakeDb([_connection(1), _connection(2, email="seo@bisiesto.es"),
                  _connection(3, email="proyectos.seo@sietepar.com")])

    result = await ga4_live.properties(db, _client(f" properties/{PROPERTY} "), list_fn=list_fn, today=TODAY)

    assert result == {"client_id": 28, "client_name": "Cigarral de Caravantes", "property_id": PROPERTY,
                      "account": "seo@bisiesto.es", "data_available_until": "2026-10-25", "error": None,
                      "reconnect_required": [], "missing_scope": []}
    assert db.commits == 1


async def test_sin_cuenta_que_la_vea_dice_por_que(service):
    fake = service(_FakeService())
    list_fn = _visible(token_1=GscAuthError("expired"), token_2=Ga4Error("missing_scope"), token_3=["111111"])
    connections = [_connection(1), _connection(2, email="seo@bisiesto.es"), _connection(3, email="otra@x.es")]

    result = await ga4_live.properties(_FakeDb(connections), _client(), list_fn=list_fn, today=TODAY)

    assert (result["account"], result["data_available_until"], result["error"]) == (None, None, "missing_scope")
    assert result["reconnect_required"] == ["digital@magnify.ing"]
    assert result["missing_scope"] == ["seo@bisiesto.es"]
    assert fake.calls == []

    with pytest.raises(ga4_live.Ga4LiveError) as exc:
        await _query(db=_FakeDb(connections), list_fn=list_fn)
    assert (exc.value.status, exc.value.code) == (403, "missing_scope")
    assert "seo@bisiesto.es" in exc.value.message and "digital@magnify.ing" in exc.value.message

    ga4_live._properties_cache.clear()
    with pytest.raises(ga4_live.Ga4LiveError) as exc:
        await _query(list_fn=_visible(token_1=["111111"]))
    assert (exc.value.status, exc.value.code) == (403, "no_access")


async def test_property_id_tiene_que_ser_la_del_cliente(service):
    fake = service(_FakeService())

    with pytest.raises(ga4_live.Ga4LiveError) as exc:
        await _query(property_id="111111")
    assert (exc.value.status, exc.value.code) == (422, "unknown_property")
    assert PROPERTY in exc.value.message
    assert fake.calls == []

    result = await _query(property_id=f"properties/{PROPERTY}")
    assert result["property_id"] == PROPERTY


@pytest.mark.parametrize("property_id, connections, code", [
    (None, [_connection()], "no_property"),
    (PROPERTY, [], "not_connected"),
    (PROPERTY, [_connection(status="reconnect_required")], "reconnect_required"),
])
async def test_sin_propiedad_o_sin_conexion(service, property_id, connections, code):
    service(_FakeService())

    with pytest.raises(ga4_live.Ga4LiveError) as exc:
        await ga4_live.properties(_FakeDb(connections), _client(property_id), list_fn=_visible(), today=TODAY)

    assert (exc.value.status, exc.value.code) == (409, code)


async def test_lo_que_ve_cada_cuenta_se_reutiliza_unos_minutos(service):
    service(_FakeService())
    calls = []
    inner = _visible(token_1=[PROPERTY])

    async def list_fn(token):
        calls.append(token)
        return await inner(token)

    await _query(list_fn=list_fn)
    await _query(list_fn=list_fn)

    assert calls == ["v1:token-1"]


# ── Ruta ─────────────────────────────────────────────────────────────


@pytest.fixture
def route(monkeypatch):
    """La ruta con el servicio sustituido: devuelve lo que recibió el servicio."""
    seen: dict = {}

    async def fake_query(db, client, **kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(client_ga4, "get_client_or_404", AsyncMock(return_value=_client()))
    monkeypatch.setattr(ga4_live, "query", fake_query)
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
            return await http.post("/api/clients/28/ga4/query", json=body)
    finally:
        app.dependency_overrides.clear()


BODY = {"start_date": "2026-09-01", "end_date": "2026-09-30", "dimensions": ["sessionDefaultChannelGroup"],
        "metrics": ["sessions"],
        "filters": [{"dimension": "sessionSourceMedium", "operator": "equals", "expression": "google / organic"}]}


async def test_ruta_pasa_los_parametros_con_sus_valores_por_defecto(route):
    response = await _post(_user("clients"), BODY)

    assert response.status_code == 200, response.text
    assert route["filters"] == [{"dimension": "sessionSourceMedium", "operator": "equals",
                                 "expression": "google / organic"}]
    assert (route["limit"], route["offset"], route["order_by"], route["property_id"]) == (1000, 0, [], None)
    assert (route["dimensions"], route["metrics"]) == (["sessionDefaultChannelGroup"], ["sessions"])
    assert route["start_date"] == date(2026, 9, 1)


async def test_ruta_sin_lectura_de_clientes_es_403(route):
    response = await _post(_user("tasks"), BODY)
    assert response.status_code == 403


async def test_ruta_cliente_que_no_existe_es_404(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(client_ga4, "get_client_or_404",
                        AsyncMock(side_effect=HTTPException(status_code=404, detail="Client not found")))
    response = await _post(_user("clients"), BODY)
    assert response.status_code == 404


@pytest.mark.parametrize("change", [
    {"dimensions": ["date", "country", "city", "eventName", "pagePath", "landingPage"]},
    {"dimensions": ["date", "date"]},
    {"dimensions": ["hour"]},
    {"metrics": []},
    {"metrics": ["sessions", "sessions"]},
    {"metrics": ["bounceRate"]},
    {"filters": [{"dimension": "hour", "operator": "equals", "expression": "1"}]},
    {"filters": [{"dimension": "country", "operator": "startsWith", "expression": "S"}]},
    {"filters": [{"dimension": "country", "operator": "equals", "expression": ""}]},
    {"limit": 100001},
    {"offset": -1},
    {"start_date": "01/09/2026"},
])
async def test_ruta_rechaza_parametros_no_validos(route, change):
    response = await _post(_user("clients"), {**BODY, **change})
    assert response.status_code == 422
    assert route == {}


async def test_ruta_devuelve_el_error_del_servicio_con_codigo_y_mensaje(route, monkeypatch):
    async def failing(*_args, **_kwargs):
        raise ga4_live.Ga4LiveError(409, "no_property", "El cliente #28 no tiene propiedad de GA4")
    monkeypatch.setattr(ga4_live, "query", failing)

    response = await _post(_user("clients"), BODY)

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "no_property", "message": "El cliente #28 no tiene propiedad de GA4"}

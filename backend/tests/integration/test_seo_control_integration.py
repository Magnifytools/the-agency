"""Control SEO contra Postgres real: sumas, posición ponderada, ventana compartida
con el estado del cliente, estados, permisos y términos de marca (con Deshacer)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio

from backend.db.models import (
    Client, ClientStatus, GscConnection, GscDaily, GscDetailSync, GscPageDaily, GscQueryDaily, GscSiteSync,
)
from backend.services import seo_control
from backend.services.client_status import Viewer, portfolio

pytestmark = pytest.mark.integration

SITE = "sc-domain:acme.com"
END = date(2026, 10, 18)
WINDOW = seo_control.seo_window(END)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_cache():
    seo_control.clear_cache()
    yield
    seo_control.clear_cache()


async def _connection(db, status="connected"):
    connection = GscConnection(google_email=f"{status}@magnify.ing", refresh_token="v1:x", status=status,
                               connected_at=datetime.now(UTC))
    db.add(connection)
    await db.flush()
    return connection


async def _client(db, gsc_url=SITE, brand_terms=None, name="Acme"):
    client = Client(name=name, status=ClientStatus.active, gsc_url=gsc_url, brand_terms=brand_terms or [])
    db.add(client)
    await db.flush()
    return client


async def _synced(db, *, site=SITE, last=END, detail_last=END, connection_id=None):
    now = datetime.now(UTC)
    db.add(GscSiteSync(site_url=site, backfilled_at=now, last_synced_at=now, last_data_date=last,
                       connection_id=connection_id))
    db.add(GscDetailSync(site_url=site, backfilled_at=now, last_synced_at=now, last_data_date=detail_last))
    await db.flush()


def _day(offset: int) -> date:
    """offset 0 = END; 27 = primer día de la ventana; 28..55 = la anterior."""
    return END - timedelta(days=offset)


async def _seed(db, site=SITE):
    """Totales y detalle con cifras redondas para comprobar sumas y ponderación."""
    daily = [
        # (día, clics, impresiones, posición)
        (0, 60, 600, 2.0),
        (27, 40, 400, 7.0),       # primer día de la ventana
        (28, 30, 500, 10.0),      # último de la anterior
        (55, 20, 500, 4.0),       # primer día de la anterior
        (56, 999, 9999, 1.0),     # fuera: antes de la anterior
        (-1, 999, 9999, 1.0),     # fuera: después del final
    ]
    for offset, clicks, impressions, position in daily:
        db.add(GscDaily(site_url=site, date=_day(offset), clicks=clicks, impressions=impressions, position=position))
    queries = [
        (0, "acme tienda", 30, 100, 1.0),
        (27, "Acme Tienda", 10, 50, 2.0),
        (0, "zapatos rojos", 20, 300, 4.0),
        (28, "zapatos rojos", 25, 300, 6.0),
        (55, "zapatos azules", 10, 100, 9.0),   # perdida
        (0, "botas", 5, 40, 3.0),               # nueva
        (56, "zapatos rojos", 500, 500, 1.0),   # fuera de la ventana
    ]
    for offset, query, clicks, impressions, position in queries:
        db.add(GscQueryDaily(site_url=site, date=_day(offset), query=query, clicks=clicks,
                             impressions=impressions, position=position))
    pages = [
        (0, "https://acme.com/", 50, 500, 1.5),
        (28, "https://acme.com/", 40, 600, 2.5),
        (0, "https://acme.com/blog/zapatos", 30, 300, 5.0),
        (27, "https://acme.com/blog/botas", 10, 100, 8.0),
        (55, "https://acme.com/blog/zapatos", 5, 100, 9.0),
        (0, "https://tienda.acme.com/p/1", 5, 50, 3.0),
    ]
    for offset, page, clicks, impressions, position in pages:
        db.add(GscPageDaily(site_url=site, date=_day(offset), page=page, clicks=clicks,
                            impressions=impressions, position=position))
    await db.flush()


@pytest_asyncio.fixture
async def acme(db_session):
    connection = await _connection(db_session)
    client = await _client(db_session, brand_terms=["Acme"])
    await _synced(db_session, connection_id=connection.id)
    await _seed(db_session)
    return client


# ── Sumas, posición y ventana ────────────────────────────────────────


async def test_resumen_suma_la_ventana_y_pondera_la_posicion(admin_client, acme):
    resp = await admin_client.get(f"/api/clients/{acme.id}/seo")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["window"] == {"start": "2026-09-21", "end": "2026-10-18", "previous_start": "2026-08-24",
                              "previous_end": "2026-09-20", "days": 28}
    current, previous = body["totals"]["current"], body["totals"]["previous"]
    assert current["clicks"] == 100 and current["impressions"] == 1000
    # (2·600 + 7·400) / 1000 = 4,0 — no la media simple (4,5).
    assert current["position"] == 4.0
    assert previous["clicks"] == 50 and previous["impressions"] == 1000
    assert previous["position"] == 7.0  # (10·500 + 4·500) / 1000
    assert body["totals"]["change"] == {"clicks_pct": 100.0, "impressions_pct": 0.0,
                                        "ctr_delta": 0.05, "position_delta": 3.0}

    brand = body["brand"]
    assert brand["terms"] == ["Acme"]
    assert brand["current"] == {
        "brand": {"clicks": 40, "impressions": 150},
        "non_brand": {"clicks": 25, "impressions": 340},
        "unclassified": {"clicks": 35, "impressions": 510},
    }
    assert brand["previous"]["non_brand"] == {"clicks": 35, "impressions": 400}
    assert brand["previous"]["unclassified"] == {"clicks": 15, "impressions": 600}
    assert len(brand["trend"]) == 16 and brand["trend"][-1]["week_end"] == "2026-10-18"
    assert brand["trend"][-1]["brand_clicks"] == 30
    assert body["coverage"]["query_clicks_share"] == 0.65

    sections = {s["key"]: s for s in body["sections"]}
    assert set(sections) == {"/", "/blog", "tienda.acme.com"}
    assert sections["/blog"]["clicks"] == 40 and sections["/blog"]["previous_clicks"] == 5
    assert sections["/blog"]["pages"] == 2
    assert sections["/blog"]["position"] == 5.75  # (5·300 + 8·100) / 400

    gainers = [r["query"] for r in body["queries"]["gainers"]]
    assert gainers == ["acme tienda", "Acme Tienda", "botas"]
    losers = body["queries"]["losers"]
    assert [r["query"] for r in losers] == ["zapatos azules", "zapatos rojos"]
    assert losers[0]["state"] == "lost" and losers[1]["position_delta"] == 2.0


async def test_la_ventana_es_la_del_estado_del_cliente(admin_client, db_session, acme):
    body = (await admin_client.get(f"/api/clients/{acme.id}/seo")).json()
    status = (await portfolio(db_session, [acme], Viewer(is_admin=True, tasks=True, digests=True,
                                                         timesheet=True), today=END + timedelta(days=2)))[0]
    assert status["seo"]["source"] == "search_console"
    assert status["seo"]["as_of"] == body["window"]["end"]
    assert status["seo"]["clicks"] == body["totals"]["current"]["clicks"]
    assert status["seo"]["clicks_previous"] == body["totals"]["previous"]["clicks"]


async def test_el_final_es_el_ultimo_dia_que_tienen_totales_y_detalle(admin_client, db_session):
    connection = await _connection(db_session)
    client = await _client(db_session, gsc_url="sc-domain:lento.com")
    await _synced(db_session, site="sc-domain:lento.com", last=END, detail_last=END - timedelta(days=2),
                  connection_id=connection.id)
    body = (await admin_client.get(f"/api/clients/{client.id}/seo?days=7")).json()
    assert body["window"]["end"] == "2026-10-16" and body["window"]["days"] == 7
    assert body["totals"]["current"]["clicks"] == 0
    assert body["totals"]["current"]["position"] is None
    assert body["coverage"]["query_clicks_share"] is None


async def test_dias_solo_7_o_28(admin_client, acme):
    assert (await admin_client.get(f"/api/clients/{acme.id}/seo?days=30")).status_code == 422


# ── Listados ─────────────────────────────────────────────────────────


async def test_consultas_por_marca_busqueda_y_limite(admin_client, acme):
    url = f"/api/clients/{acme.id}/seo/queries"
    rows = (await admin_client.get(url, params={"brand": "non_brand"})).json()["rows"]
    assert [r["query"] for r in rows] == ["botas"]
    assert rows[0]["state"] == "new" and rows[0]["is_brand"] is False

    body = (await admin_client.get(url, params={"brand": "brand", "limit": 1})).json()
    assert body["total"] == 2 and [r["query"] for r in body["rows"]] == ["acme tienda"]

    body = (await admin_client.get(url, params={"sort": "clicks_loss", "q": "ZAPATOS"})).json()
    assert [r["query"] for r in body["rows"]] == ["zapatos azules", "zapatos rojos"]

    # Por posición, el mínimo vale en las dos ventanas: sólo "zapatos rojos" (300/300).
    body = (await admin_client.get(url, params={"sort": "position_gain", "min_impressions": 100})).json()
    assert [(r["query"], r["position_delta"]) for r in body["rows"]] == [("zapatos rojos", 2.0)]
    assert (await admin_client.get(url, params={"limit": 101})).status_code == 422


async def test_paginas_por_seccion(admin_client, acme):
    url = f"/api/clients/{acme.id}/seo/pages"
    body = (await admin_client.get(url, params={"section": "/blog", "min_impressions": 0})).json()
    assert [(r["page"], r["section"]) for r in body["rows"]] == [
        ("https://acme.com/blog/zapatos", "/blog"), ("https://acme.com/blog/botas", "/blog"),
    ]
    body = (await admin_client.get(url, params={"sort": "position_gain", "min_impressions": 100})).json()
    assert [(r["page"], r["position_delta"]) for r in body["rows"]] == [
        ("https://acme.com/blog/zapatos", 4.0), ("https://acme.com/", 1.0),
    ]


# ── Estados ──────────────────────────────────────────────────────────


async def test_sin_propiedad(admin_client, db_session):
    client = await _client(db_session, gsc_url=None)
    body = (await admin_client.get(f"/api/clients/{client.id}/seo")).json()
    assert body["status"] == "no_property" and body["window"] is None and body["sections"] == []
    body = (await admin_client.get(f"/api/clients/{client.id}/seo/queries")).json()
    assert body["status"] == "no_property" and body["rows"] == []


async def test_sin_cuenta_y_cuenta_para_reconectar(admin_client, db_session):
    client = await _client(db_session, gsc_url="sc-domain:nueva.com")
    assert (await admin_client.get(f"/api/clients/{client.id}/seo")).json()["status"] == "not_connected"
    await _connection(db_session, status="reconnect_required")
    assert (await admin_client.get(f"/api/clients/{client.id}/seo")).json()["status"] == "reconnect_required"


async def test_sin_importar_e_importando(admin_client, db_session):
    connection = await _connection(db_session)
    client = await _client(db_session, gsc_url="sc-domain:nueva.com")
    url = f"/api/clients/{client.id}/seo"
    assert (await admin_client.get(url)).json()["status"] == "not_synced"

    now = datetime.now(UTC)
    db_session.add(GscSiteSync(site_url="sc-domain:nueva.com", backfilled_at=now, last_data_date=END,
                               connection_id=connection.id))
    db_session.add(GscDetailSync(site_url="sc-domain:nueva.com", last_synced_at=now, last_data_date=END))
    await db_session.flush()
    body = (await admin_client.get(url)).json()
    assert body["status"] == "backfilling" and body["last_synced_at"] is not None

    detail = await db_session.get(GscDetailSync, "sc-domain:nueva.com")
    detail.error_code = "no_access"
    await db_session.flush()
    body = (await admin_client.get(url)).json()
    assert body["status"] == "error" and body["error_code"] == "no_access"


# ── Permisos ─────────────────────────────────────────────────────────


async def test_permisos(make_member_client, member_client, admin_client, acme):
    for path in ("seo", "seo/queries", "seo/pages"):
        assert (await member_client.get(f"/api/clients/{acme.id}/{path}")).status_code == 403
        assert (await admin_client.get(f"/api/clients/999999/{path}")).status_code == 404
    reader = await make_member_client([("clients", True, False)])
    try:
        assert (await reader.get(f"/api/clients/{acme.id}/seo")).status_code == 200
        assert (await reader.get(f"/api/clients/999999/seo")).status_code == 404
    finally:
        await reader.aclose()


# ── Términos de marca ────────────────────────────────────────────────


async def test_terminos_de_marca_se_validan_y_se_deshacen(admin_client, db_session, acme):
    url = f"/api/clients/{acme.id}"
    resp = await admin_client.put(url, json={"brand_terms": ["  Acme  Corp ", "ACMECORP", "acme shop"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["brand_terms"] == ["Acme Corp", "acme shop"]

    for bad in (["ab"], ["x" * 61], [f"marca {i}" for i in range(21)], "acme"):
        assert (await admin_client.put(url, json={"brand_terms": bad})).status_code == 422
    await db_session.refresh(acme)
    assert acme.brand_terms == ["Acme Corp", "acme shop"]

    # null = sin términos (la columna no admite NULL).
    assert (await admin_client.put(url, json={"brand_terms": None})).json()["brand_terms"] == []
    assert (await admin_client.get(url)).json()["brand_terms"] == []

    # Deshacer el último cambio devuelve los términos anteriores.
    recent = (await admin_client.get("/api/changes/recent")).json()
    entry = next(e for e in recent if e["entity_type"] == "client" and e["entity_id"] == acme.id)
    undone = await admin_client.post(f"/api/changes/{entry['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert (await admin_client.get(url)).json()["brand_terms"] == ["Acme Corp", "acme shop"]


async def test_cambiar_los_terminos_cambia_el_reparto_sin_esperar_a_la_cache(admin_client, acme):
    url = f"/api/clients/{acme.id}/seo"
    assert (await admin_client.get(url)).json()["brand"]["current"]["brand"]["clicks"] == 40
    assert (await admin_client.put(f"/api/clients/{acme.id}", json={"brand_terms": ["zapatos"]})).status_code == 200
    body = (await admin_client.get(url)).json()
    assert body["brand"]["current"]["brand"] == {"clicks": 20, "impressions": 300}
    assert body["brand"]["current"]["non_brand"] == {"clicks": 45, "impressions": 190}

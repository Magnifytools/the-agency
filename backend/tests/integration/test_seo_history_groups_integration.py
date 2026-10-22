"""Historial de posiciones por consulta y grupos de URL del Control SEO contra
Postgres real: resumen mensual (idempotente), importación inicial de meses con
Google simulado, retención y purga, API (permisos, sumas, posición ponderada)
y grupos (validación, reparto, filtro de páginas y Deshacer)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.core.security import encrypt_vault_secret
from backend.db.models import (
    Client, ClientStatus, GscConnection, GscDetailSync, GscPageDaily, GscQueryDaily, GscQueryMonthly, GscSiteSync,
)
from backend.services import gsc_detail_service as detail
from backend.services import seo_control
from backend.services.gsc_detail_service import DetailRow, MonthRow
from backend.services.gsc_service import GscAuthError, GscSiteError

pytestmark = pytest.mark.integration

SITE = "sc-domain:acme.com"
TODAY = date(2026, 10, 22)
YESTERDAY = TODAY - timedelta(days=1)
END = date(2026, 10, 18)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_cache():
    seo_control.clear_cache()
    yield
    seo_control.clear_cache()


async def _connection(db, email="seo@magnify.ing", token="v1:x"):
    connection = GscConnection(google_email=email, refresh_token=token, status="connected",
                               connected_at=datetime.now(UTC))
    db.add(connection)
    await db.flush()
    return connection


async def _client(db, gsc_url=SITE, name="Acme", status=ClientStatus.active, groups=None):
    client = Client(name=name, status=status, gsc_url=gsc_url, seo_page_groups=groups or [])
    db.add(client)
    await db.flush()
    return client


async def _monthly(db, site=SITE):
    rows = (await db.execute(select(GscQueryMonthly).where(GscQueryMonthly.site_url == site)
                             .order_by(GscQueryMonthly.month, GscQueryMonthly.query))).scalars().all()
    return {(r.query, r.month): (r.clicks, r.impressions, r.weighted_position_sum) for r in rows}


def _q(day, query, clicks, impressions, position, site=SITE):
    return GscQueryDaily(site_url=site, date=day, query=query, clicks=clicks, impressions=impressions,
                         position=position)


def _never(*_args):
    raise AssertionError("no debe pedir meses a Google")


# ── Resumen mensual del detalle ──────────────────────────────────────


async def test_resume_los_meses_completos_y_repetirlo_da_lo_mismo(db_session):
    now = datetime.now(UTC)
    db_session.add(GscDetailSync(site_url=SITE, backfilled_at=now, monthly_backfilled_at=now,
                                 last_data_date=date(2026, 10, 19)))
    db_session.add_all([
        _q(date(2026, 6, 30), "zapatos", 9, 9, 1.0),      # junio no está entero: no se toca
        _q(date(2026, 7, 1), "zapatos", 3, 10, 2.0),
        _q(date(2026, 7, 31), "zapatos", 1, 30, 6.0),
        _q(date(2026, 7, 15), "botas", 2, 20, 4.0),
        _q(date(2026, 9, 30), "zapatos", 5, 50, 3.0),
        _q(date(2026, 10, 5), "zapatos", 7, 70, 1.0),     # octubre sin cerrar
        # Lo que trajo Google para junio y un julio viejo que se sustituye.
        GscQueryMonthly(site_url=SITE, month=date(2026, 6, 1), query="zapatos", clicks=50, impressions=500,
                        weighted_position_sum=1000.0),
        GscQueryMonthly(site_url=SITE, month=date(2026, 7, 1), query="vieja", clicks=1, impressions=1,
                        weighted_position_sum=1.0),
    ])
    await db_session.flush()

    for _ in range(2):
        await detail.sync_monthly(db_session, "v1:x", SITE, fetch_month=_never, today=TODAY)
        db_session.expire_all()
        assert await _monthly(db_session) == {
            ("zapatos", date(2026, 6, 1)): (50, 500, 1000.0),
            ("botas", date(2026, 7, 1)): (2, 20, 80.0),
            # Clics e impresiones se suman; posición ponderada: (2·10 + 6·30) / 40 = 5.
            ("zapatos", date(2026, 7, 1)): (4, 40, pytest.approx(200.0)),
            ("zapatos", date(2026, 9, 1)): (5, 50, pytest.approx(150.0)),
        }


async def test_la_primera_vez_pide_a_google_los_meses_anteriores_una_sola_vez(db_session):
    daily = {"query": [DetailRow(YESTERDAY - timedelta(days=118), "zapatos", 1, 10, 4.0),
                       DetailRow(date(2026, 8, 10), "zapatos", 2, 20, 3.0),
                       DetailRow(YESTERDAY, "zapatos", 3, 30, 2.0)], "page": []}

    async def fetch(_token, _site, start, end, dimension):
        return [r for r in daily[dimension] if start <= r.date <= end]

    calls: list = []

    async def fetch_month(_token, site, start, end):
        calls.append((site, start, end))
        return [MonthRow("zapatos", 9, 90, 2.0), MonthRow("botas", 1, 10, 7.0)] if start == date(2026, 6, 1) else []

    await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=fetch, fetch_month=fetch_month, today=TODAY)

    # Un mes por petición, de julio de 2025 (16 meses) a junio de 2026 (el que el detalle no tiene entero).
    assert [c[1] for c in calls] == [detail.add_months(date(2025, 7, 1), i) for i in range(12)]
    assert calls[-1] == (SITE, date(2026, 6, 1), date(2026, 6, 30))
    state = await db_session.get(GscDetailSync, SITE)
    assert state.monthly_backfilled_at is not None and state.error_code is None
    monthly = await _monthly(db_session)
    assert monthly[("zapatos", date(2026, 6, 1))] == (9, 90, pytest.approx(180.0))
    assert monthly[("botas", date(2026, 6, 1))] == (1, 10, pytest.approx(70.0))
    assert monthly[("zapatos", date(2026, 8, 1))] == (2, 20, pytest.approx(60.0))
    assert not any(m >= date(2026, 10, 1) for _, m in monthly)

    calls.clear()
    await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=fetch, fetch_month=fetch_month, today=TODAY)
    assert calls == []


async def test_un_fallo_de_google_en_los_meses_no_bloquea_y_se_reintenta(db_session):
    daily = {"query": [DetailRow(date(2026, 6, 25), "y", 1, 1, 1.0), DetailRow(date(2026, 8, 10), "zapatos", 2, 20, 3.0),
                       DetailRow(YESTERDAY, "x", 1, 1, 1.0)],
             "page": []}

    async def fetch(_token, _site, start, end, dimension):
        return [r for r in daily[dimension] if start <= r.date <= end]

    async def broken(*_):
        raise GscSiteError("rate_limited")

    await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=fetch, fetch_month=broken, today=TODAY)

    state = await db_session.get(GscDetailSync, SITE)
    assert state.monthly_backfilled_at is None
    assert state.error_code is None and state.backfilled_at is not None   # el Control SEO sigue
    # El resumen del detalle se hace igual.
    assert ("zapatos", date(2026, 8, 1)) in await _monthly(db_session)

    calls: list = []

    async def fixed(_token, _site, start, _end):
        calls.append(start)
        return []

    await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=fetch, fetch_month=fixed, today=TODAY)
    assert calls and (await db_session.get(GscDetailSync, SITE)).monthly_backfilled_at is not None


async def test_un_token_caido_en_los_meses_marca_la_cuenta(db_session):
    connection = await _connection(db_session)
    await _client(db_session)
    db_session.add(GscSiteSync(site_url=SITE, connection_id=connection.id))
    await db_session.flush()

    async def fetch(_token, _site, _start, end, dimension):
        return [DetailRow(end, "q", 1, 1, 1.0)] if dimension == "query" else []

    async def fetch_month(*_):
        raise GscAuthError("invalid_grant")

    @asynccontextmanager
    async def factory():
        yield db_session

    result = await detail.sync_all_detail(factory, fetch=fetch, fetch_month=fetch_month, today=TODAY)

    assert result["status"] == "reconnect_required"
    assert (await db_session.get(GscConnection, connection.id)).status == "reconnect_required"


async def test_retencion_16_meses_y_webs_sin_cliente_activo(db_session):
    await _client(db_session, SITE, name="Activo")
    await _client(db_session, "sc-domain:antiguo.com", name="Antiguo", status=ClientStatus.finished)
    for site, month in ((SITE, date(2025, 6, 1)), (SITE, date(2025, 7, 1)),
                        ("sc-domain:antiguo.com", date(2026, 9, 1)), ("sc-domain:cambiada.com", date(2026, 9, 1))):
        db_session.add(GscQueryMonthly(site_url=site, month=month, query="q", clicks=1, impressions=1,
                                       weighted_position_sum=1.0))
    await db_session.flush()

    await detail.prune(db_session, today=TODAY)

    rows = (await db_session.execute(select(GscQueryMonthly.site_url, GscQueryMonthly.month))).all()
    # Hoy, 22 oct 2026: se guarda desde julio de 2025.
    assert [(r.site_url, r.month) for r in rows] == [(SITE, date(2025, 7, 1))]


async def test_desconectar_purgando_borra_tambien_el_historial(admin_client, db_session):
    mine = await _connection(db_session, "a@magnify.ing", encrypt_vault_secret("token-a"))
    other = await _connection(db_session, "b@magnify.ing", encrypt_vault_secret("token-b"))
    for site, cid in (("sc-domain:a.com", mine.id), ("sc-domain:b.com", other.id)):
        db_session.add_all([
            GscSiteSync(site_url=site, connection_id=cid, last_data_date=YESTERDAY),
            GscQueryMonthly(site_url=site, month=date(2026, 9, 1), query="q", clicks=1, impressions=1,
                            weighted_position_sum=1.0),
            GscDetailSync(site_url=site, last_data_date=YESTERDAY, monthly_backfilled_at=datetime.now(UTC)),
        ])
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{mine.id}/disconnect", json={"purge_data": True})

    assert resp.status_code == 200
    db_session.expire_all()
    sites = set((await db_session.scalars(select(GscQueryMonthly.site_url))).all())
    assert sites == {"sc-domain:b.com"}
    # Sin la marca: si otra cuenta la ve, la próxima pasada vuelve a traer los meses.
    assert await db_session.get(GscDetailSync, "sc-domain:a.com") is None


# ── API: historial de una consulta ───────────────────────────────────


@pytest_asyncio.fixture
async def acme(db_session):
    connection = await _connection(db_session)
    client = await _client(db_session, groups=[
        {"name": "Guías", "rules": [{"type": "prefix", "value": "/blog/guias/"}]},
        {"name": "Blog", "rules": [{"type": "prefix", "value": "/blog/"}]},
        {"name": "Vacío", "rules": [{"type": "contains", "value": "nada"}]},
    ])
    now = datetime.now(UTC)
    db_session.add(GscSiteSync(site_url=SITE, backfilled_at=now, last_synced_at=now, last_data_date=END,
                               connection_id=connection.id))
    db_session.add(GscDetailSync(site_url=SITE, backfilled_at=now, last_synced_at=now, last_data_date=END,
                                 monthly_backfilled_at=now))
    for month, query, clicks, impressions, weighted in (
        (date(2025, 7, 1), "zapatos", 4, 40, 400.0),     # posición 10
        (date(2026, 8, 1), "zapatos", 10, 100, 500.0),   # 5
        (date(2026, 9, 1), "zapatos", 20, 200, 600.0),   # 3
        (date(2026, 9, 1), "botas", 1, 10, 80.0),
        (date(2025, 6, 1), "zapatos", 99, 99, 99.0),     # fuera de los 16 meses
    ):
        db_session.add(GscQueryMonthly(site_url=SITE, month=month, query=query, clicks=clicks,
                                       impressions=impressions, weighted_position_sum=weighted))
    db_session.add_all([
        _q(END, "zapatos", 10, 100, 2.0),
        _q(END - timedelta(days=5), "zapatos", 2, 20, 4.0),
        _q(END - timedelta(days=5), "botas", 1, 1, 9.0),
    ])
    for offset, page, clicks, impressions, position in (
        (0, "https://acme.com/blog/guias/zapatos", 10, 100, 2.0),
        (0, "https://acme.com/blog/noticias", 20, 200, 5.0),
        (30, "https://acme.com/blog/noticias", 5, 100, 8.0),
        (0, "https://acme.com/p/1", 30, 300, 3.0),
    ):
        db_session.add(GscPageDaily(site_url=SITE, date=END - timedelta(days=offset), page=page, clicks=clicks,
                                    impressions=impressions, position=position))
    await db_session.flush()
    return client


async def test_historial_por_meses_y_por_dias(admin_client, acme):
    resp = await admin_client.get(f"/api/clients/{acme.id}/seo/queries/history", params={"query": "zapatos"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok" and body["query"] == "zapatos" and body["monthly_backfilled"] is True
    assert body["months"] == [
        {"month": "2025-07-01", "clicks": 4, "impressions": 40, "position": 10.0},
        {"month": "2026-08-01", "clicks": 10, "impressions": 100, "position": 5.0},
        {"month": "2026-09-01", "clicks": 20, "impressions": 200, "position": 3.0},
    ]
    # Desde el primer día guardado de la propiedad hasta el final; días sin fila = 0 y sin posición.
    days = body["days"]
    assert [d["date"] for d in days] == [(END - timedelta(days=i)).isoformat() for i in range(5, -1, -1)]
    assert days[0] == {"date": (END - timedelta(days=5)).isoformat(), "clicks": 2, "impressions": 20, "position": 4.0}
    assert days[1]["clicks"] == 0 and days[1]["position"] is None
    assert days[-1]["position"] == 2.0


async def test_historial_de_una_consulta_que_no_salio_algun_mes(admin_client, acme):
    body = (await admin_client.get(f"/api/clients/{acme.id}/seo/queries/history", params={"query": "botas"})).json()
    assert [(m["month"], m["clicks"], m["position"]) for m in body["months"]] == [
        ("2025-07-01", 0, None), ("2026-08-01", 0, None), ("2026-09-01", 1, 8.0)]


async def test_historial_sin_propiedad(admin_client, db_session):
    client = await _client(db_session, gsc_url=None, name="Sin web")
    body = (await admin_client.get(f"/api/clients/{client.id}/seo/queries/history", params={"query": "x"})).json()
    assert body["status"] == "no_property" and body["months"] == [] and body["days"] == []


async def test_las_consultas_llevan_su_tendencia_de_meses(admin_client, acme):
    body = (await admin_client.get(f"/api/clients/{acme.id}/seo/queries",
                                   params={"min_impressions": 0, "limit": 10})).json()
    assert body["trend_months"] == ["2025-07-01", "2026-08-01", "2026-09-01"]
    rows = {r["query"]: r for r in body["rows"]}
    assert rows["zapatos"]["trend"] == [10.0, 5.0, 3.0]
    assert rows["botas"]["trend"] == [None, None, 8.0]
    summary = (await admin_client.get(f"/api/clients/{acme.id}/seo")).json()
    assert summary["queries"]["trend_months"] == body["trend_months"]
    assert all("trend" in r for r in summary["queries"]["gainers"])


# ── API: grupos de URL ───────────────────────────────────────────────


async def test_cifras_por_grupo_y_filtro_de_paginas(admin_client, acme):
    body = (await admin_client.get(f"/api/clients/{acme.id}/seo/groups")).json()
    assert body["status"] == "ok" and body["configured"] == 3
    groups = {g["key"]: g for g in body["groups"]}
    assert list(groups) == ["Guías", "Blog", "Vacío", "Sin grupo"]
    # La guía entra en "Guías" (primer grupo que la acepta), no en "Blog".
    assert (groups["Guías"]["clicks"], groups["Guías"]["pages"]) == (10, 1)
    blog = groups["Blog"]
    assert (blog["clicks"], blog["previous_clicks"], blog["impressions"], blog["pages"]) == (20, 5, 200, 1)
    assert blog["position"] == 5.0 and blog["position_delta"] == 3.0
    assert groups["Vacío"]["clicks"] == 0 and groups["Vacío"]["pages"] == 0
    assert groups["Sin grupo"]["clicks"] == 30 and groups["Sin grupo"]["clicks_share"] == 0.5

    pages = (await admin_client.get(f"/api/clients/{acme.id}/seo/pages",
                                    params={"group": "Blog", "min_impressions": 0})).json()
    assert [r["page"] for r in pages["rows"]] == ["https://acme.com/blog/noticias"]
    assert pages["rows"][0]["group"] == "Blog"
    ungrouped = (await admin_client.get(f"/api/clients/{acme.id}/seo/pages",
                                        params={"group": "Sin grupo", "min_impressions": 0})).json()
    assert [r["page"] for r in ungrouped["rows"]] == ["https://acme.com/p/1"]


async def test_probar_grupos_sin_guardarlos(admin_client, db_session, acme):
    url = f"/api/clients/{acme.id}/seo/groups/preview"
    resp = await admin_client.post(url, json={"groups": [
        {"name": "Fichas", "rules": [{"type": "regex", "value": r"^/p/\d+$"}]}]})
    assert resp.status_code == 200, resp.text
    groups = {g["key"]: g for g in resp.json()["groups"]}
    assert groups["Fichas"]["pages"] == 1 and groups["Sin grupo"]["pages"] == 2
    assert (await admin_client.post(url, json={"groups": [
        {"name": "Mala", "rules": [{"type": "regex", "value": "(a+)+"}]}]})).status_code == 422
    # No se ha guardado nada.
    await db_session.refresh(acme)
    assert [g["name"] for g in acme.seo_page_groups] == ["Guías", "Blog", "Vacío"]


async def test_grupos_se_validan_al_guardar_y_se_deshacen(admin_client, db_session, acme):
    url = f"/api/clients/{acme.id}"
    new = [{"name": "  Fichas ", "rules": [{"type": "regex", "value": r" ^/p/\d+$ "}]}]
    resp = await admin_client.put(url, json={"seo_page_groups": new})
    assert resp.status_code == 200, resp.text
    assert resp.json()["seo_page_groups"] == [{"name": "Fichas", "rules": [{"type": "regex", "value": r"^/p/\d+$"}]}]

    for bad in ([{"name": "Sin grupo", "rules": [{"type": "prefix", "value": "/x"}]}],
                [{"name": "R", "rules": [{"type": "regex", "value": r"(\w+)\1"}]}],
                [{"name": f"G{i}", "rules": [{"type": "prefix", "value": "/x"}]} for i in range(31)],
                "blog"):
        assert (await admin_client.put(url, json={"seo_page_groups": bad})).status_code == 422
    body = (await admin_client.get(f"/api/clients/{acme.id}/seo/groups")).json()
    assert [g["key"] for g in body["groups"]] == ["Fichas", "Sin grupo"]

    recent = (await admin_client.get("/api/changes/recent")).json()
    entry = next(e for e in recent if e["entity_type"] == "client" and e["entity_id"] == acme.id)
    undone = await admin_client.post(f"/api/changes/{entry['id']}/undo")
    assert undone.status_code == 200, undone.text
    assert [g["name"] for g in (await admin_client.get(url)).json()["seo_page_groups"]] == ["Guías", "Blog", "Vacío"]

    # null = sin grupos.
    assert (await admin_client.put(url, json={"seo_page_groups": None})).json()["seo_page_groups"] == []


async def test_permisos(make_member_client, member_client, admin_client, acme):
    paths = [("get", "seo/groups", None), ("get", "seo/queries/history?query=zapatos", None),
             ("post", "seo/groups/preview", {"groups": []})]
    for method, path, body in paths:
        kwargs = {"json": body} if body is not None else {}
        assert (await getattr(member_client, method)(f"/api/clients/{acme.id}/{path}", **kwargs)).status_code == 403
        assert (await getattr(admin_client, method)(f"/api/clients/999999/{path}", **kwargs)).status_code == 404
    reader = await make_member_client([("clients", True, False)])
    try:
        for method, path, body in paths:
            kwargs = {"json": body} if body is not None else {}
            assert (await getattr(reader, method)(f"/api/clients/{acme.id}/{path}", **kwargs)).status_code == 200
        # Leer no basta para guardar los grupos.
        assert (await reader.put(f"/api/clients/{acme.id}", json={"seo_page_groups": []})).status_code == 403
    finally:
        await reader.aclose()

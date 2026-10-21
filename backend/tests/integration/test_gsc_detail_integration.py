"""Detalle de Search Console contra Postgres real: importación, reemplazo, retención y purga."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.core.security import encrypt_vault_secret
from backend.db.models import (
    Client, ClientStatus, GscConnection, GscDaily, GscDetailSync, GscPageDaily, GscQueryDaily, GscSiteSync,
)
from backend.services import gsc_detail_service as detail
from backend.services.gsc_detail_service import DetailRow
from backend.services.gsc_service import GscAuthError, GscSiteError

pytestmark = pytest.mark.integration

SITE = "sc-domain:ejemplo.com"
TODAY = date(2026, 10, 22)
YESTERDAY = TODAY - timedelta(days=1)


async def _connect(db, email="seo@magnify.ing", token="v1:x"):
    connection = GscConnection(google_email=email, refresh_token=token, status="connected",
                               connected_at=datetime.now(UTC))
    db.add(connection)
    await db.flush()
    return connection


async def _client(db, gsc_url=SITE, name="Ejemplo", status=ClientStatus.active):
    client = Client(name=name, status=status, gsc_url=gsc_url)
    db.add(client)
    await db.flush()
    return client


async def _assigned(db, site, connection_id, error_code=None):
    """Lo que deja el job `gsc`: qué cuenta ve la propiedad."""
    db.add(GscSiteSync(site_url=site, connection_id=connection_id, error_code=error_code))
    await db.flush()


def _factory(db):
    @asynccontextmanager
    async def factory():
        yield db
    return factory


async def _count(db, model, *where):
    return await db.scalar(select(func.count()).select_from(model).where(*where))


def _fetch_from(table: dict, calls: list | None = None):
    """Google de mentira: devuelve las filas de `table[dimension]` dentro del tramo pedido."""
    async def fetch(_token, site, start, end, dimension):
        if calls is not None:
            calls.append((site, start, end, dimension))
        return [r for r in table.get(dimension, []) if start <= r.date <= end]
    return fetch


async def test_importa_consultas_y_paginas_y_guarda_el_estado(db_session):
    calls: list = []
    table = {
        "query": [DetailRow(YESTERDAY, "zapatos", 3, 30, 4.5), DetailRow(YESTERDAY - timedelta(days=30), "botas", 1, 9, 8.0)],
        "page": [DetailRow(YESTERDAY, "https://ejemplo.com/zapatos", 3, 40, 5.0)],
    }

    written = await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=_fetch_from(table, calls), today=TODAY)

    assert written == {"query": 2, "page": 1}
    # 120 días en tramos de 14, cada tramo con las dos dimensiones.
    assert len(calls) == 9 * 2
    assert calls[0][1] == YESTERDAY - timedelta(days=119) and calls[-1][2] == YESTERDAY
    row = await db_session.get(GscQueryDaily, (SITE, YESTERDAY, "zapatos"))
    assert (row.clicks, row.impressions, row.position) == (3, 30, 4.5)
    assert await _count(db_session, GscPageDaily) == 1
    state = await db_session.get(GscDetailSync, SITE)
    assert state.backfilled_at is not None and state.error_code is None
    assert state.last_data_date == YESTERDAY
    assert (state.query_rows, state.page_rows) == (2, 1)


async def test_la_segunda_pasada_solo_pide_la_cola_y_reemplaza_el_tramo(db_session):
    old_day = YESTERDAY - timedelta(days=3)
    first = {"query": [DetailRow(old_day, "zapatos", 3, 30, 4.5), DetailRow(old_day, "desaparece", 1, 5, 9.0),
                       DetailRow(YESTERDAY - timedelta(days=40), "fuera de la cola", 2, 20, 3.0)]}
    await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=_fetch_from(first), today=TODAY)

    calls: list = []
    # Google revisa el día: "zapatos" cambia y "desaparece" ya no sale.
    second = {"query": [DetailRow(old_day, "zapatos", 4, 31, 4.0)]}
    await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=_fetch_from(second, calls), today=TODAY)

    assert {c[1:3] for c in calls} == {(old_day - timedelta(days=7), YESTERDAY)}
    db_session.expire_all()
    row = await db_session.get(GscQueryDaily, (SITE, old_day, "zapatos"))
    assert (row.clicks, row.impressions, row.position) == (4, 31, 4.0)
    assert await db_session.get(GscQueryDaily, (SITE, old_day, "desaparece")) is None
    # Lo de fuera de la cola no se toca.
    assert await _count(db_session, GscQueryDaily, GscQueryDaily.query == "fuera de la cola") == 1
    assert (await db_session.get(GscDetailSync, SITE)).query_rows == 2


async def test_poda_lo_de_mas_de_120_dias(db_session):
    await _client(db_session)
    old = YESTERDAY - timedelta(days=121)
    db_session.add_all([
        GscQueryDaily(site_url=SITE, date=old, query="vieja", clicks=1, impressions=1, position=1.0),
        GscPageDaily(site_url=SITE, date=old, page="https://ejemplo.com/vieja", clicks=1, impressions=1, position=1.0),
    ])
    await db_session.flush()

    # Una pasada normal también poda tras importar.
    await detail.sync_site_detail(db_session, "v1:x", SITE, fetch=_fetch_from({
        "query": [DetailRow(YESTERDAY - timedelta(days=119), "en la ventana", 1, 1, 1.0),
                  DetailRow(YESTERDAY, "ayer", 1, 1, 1.0)],
    }), today=TODAY)

    assert await _count(db_session, GscQueryDaily, GscQueryDaily.query == "vieja") == 0
    assert await _count(db_session, GscPageDaily) == 0
    assert await _count(db_session, GscQueryDaily, GscQueryDaily.query == "en la ventana") == 1


async def test_la_retencion_tambien_avanza_si_la_propiedad_deja_de_actualizarse(db_session):
    await _client(db_session)
    stale = YESTERDAY - timedelta(days=60)
    db_session.add_all([
        GscDetailSync(site_url=SITE, backfilled_at=datetime.now(UTC), last_data_date=stale),
        GscQueryDaily(site_url=SITE, date=stale - timedelta(days=100), query="vieja", clicks=1, impressions=1, position=1.0),
        GscQueryDaily(site_url=SITE, date=stale, query="reciente", clicks=1, impressions=1, position=1.0),
    ])
    await db_session.flush()

    await detail.prune(db_session, today=TODAY)

    assert [r.query for r in (await db_session.scalars(select(GscQueryDaily))).all()] == ["reciente"]


async def test_borra_el_detalle_de_webs_sin_cliente_activo(db_session):
    await _client(db_session, SITE, name="Activo")
    await _client(db_session, "sc-domain:antiguo.com", name="Antiguo", status=ClientStatus.finished)
    for site in (SITE, "sc-domain:antiguo.com", "sc-domain:cambiada.com"):
        db_session.add_all([
            GscQueryDaily(site_url=site, date=YESTERDAY, query="q", clicks=1, impressions=1, position=1.0),
            GscPageDaily(site_url=site, date=YESTERDAY, page="p", clicks=1, impressions=1, position=1.0),
            GscDetailSync(site_url=site, last_data_date=YESTERDAY),
        ])
    await db_session.flush()

    await detail.prune(db_session, today=TODAY)

    for model in (GscQueryDaily, GscPageDaily, GscDetailSync):
        assert set((await db_session.scalars(select(model.site_url))).all()) == {SITE}


async def test_usa_la_cuenta_de_gsc_y_apunta_las_propiedades_sin_cuenta(db_session):
    connection = await _connect(db_session)
    await _client(db_session, SITE, name="Con cuenta")
    await _client(db_session, "sc-domain:pendiente.com", name="Pendiente")
    await _client(db_session, "sc-domain:sin-acceso.com", name="Sin acceso")
    await _assigned(db_session, SITE, connection.id)
    await _assigned(db_session, "sc-domain:sin-acceso.com", None, error_code="no_access")
    calls: list = []

    result = await detail.sync_all_detail(_factory(db_session), fetch=_fetch_from({}, calls), today=TODAY)

    assert result == {"status": "ok", "synced": 1, "failed": 0, "skipped": 2}
    assert {c[0] for c in calls} == {SITE}
    assert (await db_session.get(GscDetailSync, "sc-domain:pendiente.com")).error_code == "pending_access"
    assert (await db_session.get(GscDetailSync, "sc-domain:sin-acceso.com")).error_code == "no_access"
    assert (await db_session.get(GscDetailSync, SITE)).backfilled_at is not None


async def test_un_error_de_google_se_apunta_y_sigue_con_las_demas(db_session):
    connection = await _connect(db_session)
    for name, site in (("A", "sc-domain:limitada.com"), ("B", SITE)):
        await _client(db_session, site, name=name)
        await _assigned(db_session, site, connection.id)

    async def fetch(_token, site, start, end, dimension):
        if site == "sc-domain:limitada.com":
            raise GscSiteError("rate_limited")
        return [DetailRow(end, "q", 1, 1, 1.0)] if dimension == "query" else []

    result = await detail.sync_all_detail(_factory(db_session), fetch=fetch, today=TODAY)

    assert result == {"status": "ok", "synced": 1, "failed": 1, "skipped": 0}
    failed = await db_session.get(GscDetailSync, "sc-domain:limitada.com")
    assert failed.error_code == "rate_limited" and failed.backfilled_at is None
    assert (await db_session.get(GscDetailSync, SITE)).error_code is None


async def test_token_caido_marca_la_cuenta_para_reconectar(db_session):
    connection = await _connect(db_session)
    await _client(db_session)
    await _assigned(db_session, SITE, connection.id)

    async def fetch(*_):
        raise GscAuthError("invalid_grant")

    result = await detail.sync_all_detail(_factory(db_session), fetch=fetch, today=TODAY)

    assert result["status"] == "reconnect_required" and result["failed"] == 1
    assert (await db_session.get(GscConnection, connection.id)).status == "reconnect_required"
    assert (await db_session.get(GscDetailSync, SITE)).error_code == "reconnect_required"


async def test_sin_cuenta_conectada_no_importa_pero_aplica_la_retencion(db_session):
    db_session.add(GscQueryDaily(site_url="sc-domain:huerfana.com", date=YESTERDAY, query="q",
                                 clicks=1, impressions=1, position=1.0))
    await db_session.flush()

    result = await detail.sync_all_detail(_factory(db_session), fetch=_fetch_from({}), today=TODAY)

    assert result["status"] == "not_connected"
    assert await _count(db_session, GscQueryDaily) == 0


async def test_desconectar_purgando_borra_tambien_el_detalle(admin_client, db_session):
    mine = await _connect(db_session, "a@magnify.ing", encrypt_vault_secret("token-a"))
    other = await _connect(db_session, "b@magnify.ing", encrypt_vault_secret("token-b"))
    for site, cid in (("sc-domain:a.com", mine.id), ("sc-domain:b.com", other.id)):
        db_session.add_all([
            GscSiteSync(site_url=site, connection_id=cid, last_data_date=YESTERDAY),
            GscDaily(site_url=site, date=YESTERDAY, clicks=1, impressions=1, position=1.0),
            GscQueryDaily(site_url=site, date=YESTERDAY, query="q1", clicks=1, impressions=1, position=1.0),
            GscQueryDaily(site_url=site, date=YESTERDAY, query="q2", clicks=1, impressions=1, position=1.0),
            GscPageDaily(site_url=site, date=YESTERDAY, page="p", clicks=1, impressions=1, position=1.0),
            GscDetailSync(site_url=site, last_data_date=YESTERDAY),
        ])
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{mine.id}/disconnect", json={"purge_data": True})

    assert resp.status_code == 200
    assert resp.json()["purged"] == {"gsc_sites": 1, "gsc_rows": 1, "gsc_query_rows": 2, "gsc_page_rows": 1,
                                     "ga4_properties": 0, "ga4_rows": 0}
    db_session.expire_all()
    a, b = "sc-domain:a.com", "sc-domain:b.com"
    assert await _count(db_session, GscQueryDaily, GscQueryDaily.site_url == a) == 0
    assert await _count(db_session, GscPageDaily, GscPageDaily.site_url == a) == 0
    assert await db_session.get(GscDetailSync, a) is None
    assert await _count(db_session, GscQueryDaily, GscQueryDaily.site_url == b) == 2
    assert await db_session.get(GscDetailSync, b) is not None


async def test_status_incluye_el_detalle_por_propiedad(admin_client, db_session):
    await _connect(db_session)
    await _client(db_session)
    db_session.add(GscDetailSync(site_url=SITE, backfilled_at=datetime.now(UTC), last_data_date=YESTERDAY,
                                 query_rows=10, page_rows=4))
    await _client(db_session, "sc-domain:sin-detalle.com", name="Otro")
    await db_session.flush()

    resp = await admin_client.get("/api/gsc/status")

    sites = {s["site_url"]: s for s in resp.json()["sites"]}
    assert sites[SITE]["detail"]["query_rows"] == 10 and sites[SITE]["detail"]["page_rows"] == 4
    assert sites[SITE]["detail"]["last_data_date"] == YESTERDAY.isoformat()
    assert sites["sc-domain:sin-detalle.com"]["detail"] is None


async def test_importar_detalle_ahora_es_de_admin_y_usa_el_servicio(admin_client, member_client, db_session, monkeypatch):
    from backend.services import gsc_service

    await _connect(db_session)
    await db_session.commit()
    monkeypatch.setattr(gsc_service, "configured", lambda: True)
    called = []

    async def fake_sync(factory):
        called.append(factory)
        return {"status": "ok", "synced": 0, "failed": 0, "skipped": 0}
    monkeypatch.setattr(detail, "sync_all_detail", fake_sync)

    assert (await member_client.post("/api/gsc/detail-sync")).status_code == 403
    resp = await admin_client.post("/api/gsc/detail-sync")

    assert resp.status_code == 200 and resp.json()["status"] == "ok"
    assert len(called) == 1


async def test_importar_detalle_ahora_no_pisa_una_pasada_en_marcha(admin_client, db_session, engine, monkeypatch):
    from sqlalchemy import text

    from backend.services import gsc_service
    from backend.services.job_runtime import JOB_LOCK_NAMESPACE

    await _connect(db_session)
    await db_session.commit()
    monkeypatch.setattr(gsc_service, "configured", lambda: True)

    async def fake_sync(_factory):
        raise AssertionError("no debe importar con el lock tomado")
    monkeypatch.setattr(detail, "sync_all_detail", fake_sync)

    async with engine.connect() as job:  # el job programado tiene el lock 17
        await job.execute(text("SELECT pg_advisory_lock(:ns, 17)"), {"ns": JOB_LOCK_NAMESPACE})
        try:
            resp = await admin_client.post("/api/gsc/detail-sync")
        finally:
            await job.execute(text("SELECT pg_advisory_unlock(:ns, 17)"), {"ns": JOB_LOCK_NAMESPACE})

    assert resp.status_code == 409

"""Bloque B de Control SEO contra Postgres: anotaciones, antes/después y páginas
que pierden tráfico."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio

from backend.db.models import (
    Client, ClientStatus, GscDaily, GscDetailSync, GscPageDaily, GscSiteSync, SeoAnnotation, Task, TaskStatus,
)
from backend.services import google_search_status, seo_control

pytestmark = pytest.mark.integration

SITE = "sc-domain:insights.com"
END = date(2026, 10, 18)
PAGE = "https://insights.com/blog/guia/"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_cache():
    seo_control.clear_cache()
    yield
    seo_control.clear_cache()


async def _client(db, *, groups=None):
    client = Client(name="Insights", status=ClientStatus.active, gsc_url=SITE, brand_terms=[],
                    seo_page_groups=groups or [])
    db.add(client)
    now = datetime.now(UTC)
    db.add(GscSiteSync(site_url=SITE, backfilled_at=now, last_synced_at=now, last_data_date=END))
    db.add(GscDetailSync(site_url=SITE, backfilled_at=now, last_synced_at=now, last_data_date=END))
    await db.flush()
    return client


def _day(offset: int) -> date:
    return END - timedelta(days=offset)


async def test_antes_y_despues_de_la_web_y_de_una_pagina(admin_client, db_session):
    client = await _client(db_session)
    pivot = _day(20)
    for offset in range(0, 120):
        day = _day(offset)
        after = day > pivot
        db_session.add(GscDaily(site_url=SITE, date=day, clicks=20 if after else 10, impressions=200, position=5.0))
        db_session.add(GscPageDaily(site_url=SITE, date=day, page=PAGE, clicks=8 if after else 4,
                                    impressions=50, position=6.0 if after else 8.0))
    db_session.add(GscPageDaily(site_url=SITE, date=_day(5), page="https://insights.com/otra", clicks=500,
                                impressions=900, position=1.0))
    await db_session.flush()

    site = (await admin_client.get(f"/api/clients/{client.id}/seo/impact", params={"date": pivot.isoformat()})).json()
    # Han pasado 20 días: se comparan 20 y 20 (el día del cambio no cuenta).
    assert site["result"]["days"] == 20
    assert site["result"]["before"]["clicks"] == 200 and site["result"]["after"]["clicks"] == 400
    assert site["result"]["clicks_change_pct"] == 100.0

    page = (await admin_client.get(f"/api/clients/{client.id}/seo/impact",
                                   params={"date": pivot.isoformat(), "page": "https://insights.com/blog/guia?utm=x"})).json()
    assert page["result"]["before"]["clicks"] == 80 and page["result"]["after"]["clicks"] == 160
    assert page["result"]["position_delta"] == 2.0  # de 8 a 6: mejora
    assert page["result"]["pages"] == 1

    early = (await admin_client.get(f"/api/clients/{client.id}/seo/impact", params={"date": _day(3).isoformat()})).json()
    assert early["result"] is None and early["reason"] == "too_early"

    old = (await admin_client.get(f"/api/clients/{client.id}/seo/impact",
                                  params={"date": _day(110).isoformat(), "page": PAGE})).json()
    assert old["reason"] == "outside_detail"


async def test_paginas_que_pierden_trafico(admin_client, db_session):
    client = await _client(db_session)
    falling, steady = "https://insights.com/cae", "https://insights.com/estable"
    for offset in range(0, 112):
        day = _day(offset)
        db_session.add(GscPageDaily(site_url=SITE, date=day, page=falling,
                                    clicks=1 if offset < 28 else 5, impressions=100, position=4.0 if offset < 28 else 4.2))
        db_session.add(GscPageDaily(site_url=SITE, date=day, page=steady, clicks=5, impressions=100, position=3.0))
    await db_session.flush()

    body = (await admin_client.get(f"/api/clients/{client.id}/seo/decay")).json()
    assert body["windows"] == 4
    assert [row["page"] for row in body["rows"]] == [falling]
    row = body["rows"][0]
    assert row["current"]["clicks"] == 28 and row["peak"]["clicks"] == 140
    assert row["lost_clicks"] == 112 and row["drop_pct"] == -80.0
    assert row["cause"] == "ctr"  # mismas impresiones, misma posición: menos clics por impresión


async def test_anotaciones_juntan_notas_google_y_tareas(admin_client, db_session, admin_user, _no_real_google_status):
    client = await _client(db_session)
    _no_real_google_status.return_value = google_search_status.parse_incidents([
        {"begin": "2026-09-24T16:15:00+00:00", "end": "2026-10-08T08:00:00+00:00",
         "external_desc": "September 2026 spam update", "service_name": "Ranking", "uri": "incidents/x"},
        {"begin": "2025-01-01T00:00:00+00:00", "external_desc": "Fuera del rango", "service_name": "Ranking"},
    ])
    db_session.add(Task(title="Reescribir la guía", client_id=client.id, status=TaskStatus.completed,
                        completed_at=datetime(2026, 10, 2, 10), link_url=PAGE, created_by=admin_user.id))
    db_session.add(Task(title="Sin URL", client_id=client.id, status=TaskStatus.completed,
                        completed_at=datetime(2026, 10, 2, 10), created_by=admin_user.id))
    await db_session.flush()

    created = await admin_client.post(f"/api/clients/{client.id}/seo/annotations",
                                      json={"date": "2026-10-05", "text": "  Migración   de la web  "})
    assert created.status_code == 201, created.text
    body = (await admin_client.get(f"/api/clients/{client.id}/seo/annotations",
                                   params={"from": "2026-09-01", "to": "2026-10-18"})).json()
    assert body["google_available"] is True
    kinds = [(item["kind"], item["title"]) for item in body["items"]]
    assert kinds == [
        ("google", "Actualización de Google: September 2026 spam update"),
        ("task", "Tarea cerrada: Reescribir la guía"),
        ("manual", "Migración de la web"),
    ]
    annotation_id = body["items"][2]["id"]
    assert (await admin_client.delete(f"/api/clients/{client.id}/seo/annotations/{annotation_id}")).status_code == 204
    assert await db_session.get(SeoAnnotation, annotation_id) is None


async def test_un_lector_de_clientes_sin_tareas_no_ve_las_tareas(make_member_client, db_session, admin_user):
    member_client = await make_member_client([("clients", True, False)])
    client = await _client(db_session)
    db_session.add(Task(title="Privada", client_id=client.id, status=TaskStatus.completed,
                        completed_at=datetime(2026, 10, 2, 10), link_url=PAGE, created_by=admin_user.id))
    await db_session.flush()
    res = await member_client.get(f"/api/clients/{client.id}/seo/annotations",
                                  params={"from": "2026-09-01", "to": "2026-10-18"})
    assert res.status_code == 200
    assert all(item["kind"] != "task" for item in res.json()["items"])
    # Escribir notas pide escritura de clientes.
    denied = await member_client.post(f"/api/clients/{client.id}/seo/annotations", json={"date": "2026-10-05", "text": "x"})
    assert denied.status_code == 403

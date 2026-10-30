"""Search Console propio contra Postgres real: importación, resumen mensual y digest."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.db.models import Client, ClientStatus, GscConnection, GscDaily, GscSiteSync
from backend.services import gsc_service
from backend.services.digest_collector import collect_digest_data
from backend.services.gsc_service import DailyRow, GscAuthError, GscSiteError

pytestmark = pytest.mark.integration

SITE = "sc-domain:ejemplo.com"


async def _connect(db, status="connected", email="seo@magnify.ing", token="v1:x"):
    connection = GscConnection(google_email=email, refresh_token=token, status=status,
                               connected_at=datetime.now(UTC))
    db.add(connection)
    await db.flush()
    return connection


def _sees(*sites, permission="siteOwner"):
    """Cuenta de mentira que ve estas propiedades (o todas si no se dice ninguna)."""
    async def list_fn(_token):
        return [{"site_url": s, "permission": permission} for s in sites]
    return list_fn


async def _sees_everything(db):
    return _sees(*(await gsc_service.tracked_sites(db)))


async def _client(db, gsc_url=SITE, name="Ejemplo"):
    client = Client(name=name, status=ClientStatus.active, gsc_url=gsc_url)
    db.add(client)
    await db.flush()
    return client


def _session_factory(db):
    @asynccontextmanager
    async def factory():
        yield db
    return factory


def _days(start: date, end: date, *, clicks=10, impressions=100, position=10.0):
    day, out = start, []
    while day <= end:
        out.append(DailyRow(day, clicks, impressions, position))
        day += timedelta(days=1)
    return out


async def test_first_sync_backfills_16_months_then_only_the_tail(db_session):
    today = date(2026, 10, 18)
    calls = []

    async def fetch(_token, site, start, end):
        calls.append((site, start, end))
        return _days(end - timedelta(days=2), end)

    await gsc_service.sync_site(db_session, "v1:x", SITE, fetch=fetch, today=today)
    await gsc_service.sync_site(db_session, "v1:x", SITE, fetch=fetch, today=today)

    first, second = calls
    assert first == (SITE, date(2026, 10, 17) - timedelta(days=gsc_service.BACKFILL_DAYS), date(2026, 10, 17))
    assert second == (SITE, date(2026, 10, 10), date(2026, 10, 17))
    state = await db_session.get(GscSiteSync, SITE)
    assert state.backfilled_at is not None and state.last_data_date == date(2026, 10, 17)
    assert state.error_code is None


async def test_resync_overwrites_revised_days(db_session):
    async def fetch_v1(*_):
        return [DailyRow(date(2026, 9, 1), 5, 50, 9.0)]

    async def fetch_v2(*_):
        return [DailyRow(date(2026, 9, 1), 7, 70, 8.0)]

    await gsc_service.sync_site(db_session, "v1:x", SITE, fetch=fetch_v1, today=date(2026, 9, 5))
    await gsc_service.sync_site(db_session, "v1:x", SITE, fetch=fetch_v2, today=date(2026, 9, 5))

    row = await db_session.get(GscDaily, (SITE, date(2026, 9, 1)))
    assert (row.clicks, row.impressions, row.position) == (7, 70, 8.0)
    assert await db_session.scalar(select(func.count()).select_from(GscDaily)) == 1


async def test_site_error_is_recorded_and_other_sites_continue(db_session):
    await _connect(db_session)
    await _client(db_session, "sc-domain:sin-acceso.com", name="A")
    await _client(db_session, SITE, name="B")

    async def fetch(_token, site, start, end):
        if site == "sc-domain:sin-acceso.com":
            raise GscSiteError("no_access")
        return _days(end, end)

    result = await gsc_service.sync_all(_session_factory(db_session), fetch=fetch, list_fn=await _sees_everything(db_session), today=date(2026, 10, 18))

    assert result == {"status": "ok", "synced": 1, "failed": 1}
    failed = await db_session.get(GscSiteSync, "sc-domain:sin-acceso.com")
    assert failed.error_code == "no_access" and failed.backfilled_at is None


async def test_revoked_token_marks_connection_for_reconnect(db_session):
    await _connect(db_session)
    await _client(db_session)

    async def fetch(*_):
        raise GscAuthError("invalid_grant")

    result = await gsc_service.sync_all(_session_factory(db_session), fetch=fetch, list_fn=await _sees_everything(db_session))

    assert result["status"] == "reconnect_required"
    assert (await db_session.scalar(select(GscConnection))).status == "reconnect_required"


async def _imported(db, *, last_data_date):
    db.add(GscSiteSync(site_url=SITE, backfilled_at=datetime.now(UTC), last_data_date=last_data_date))
    await db.flush()


async def test_month_summary_statuses(db_session):
    sept = (date(2026, 9, 1), date(2026, 9, 30))
    assert (await gsc_service.month_summary(db_session, None, *sept))["status"] == "no_property"
    assert (await gsc_service.month_summary(db_session, SITE, *sept))["status"] == "not_connected"
    await _connect(db_session)
    assert (await gsc_service.month_summary(db_session, SITE, *sept))["status"] == "not_synced"
    await _imported(db_session, last_data_date=date(2026, 9, 28))
    incomplete = await gsc_service.month_summary(db_session, SITE, *sept)
    assert incomplete == {"status": "incomplete", "site_url": SITE, "last_data_date": "2026-09-28"}


async def test_month_summary_sums_and_weights_position_by_impressions(db_session):
    await _connect(db_session)
    await _imported(db_session, last_data_date=date(2026, 10, 15))
    db_session.add_all([
        # Septiembre: un día con muchas impresiones en posición 2 y otro con pocas en 20.
        GscDaily(site_url=SITE, date=date(2026, 9, 1), clicks=90, impressions=900, position=2.0),
        GscDaily(site_url=SITE, date=date(2026, 9, 2), clicks=10, impressions=100, position=20.0),
        # Agosto
        GscDaily(site_url=SITE, date=date(2026, 8, 10), clicks=80, impressions=1000, position=5.0),
        # Septiembre del año anterior
        GscDaily(site_url=SITE, date=date(2025, 9, 15), clicks=50, impressions=500, position=8.0),
        # Fuera de todos los periodos: no debe contar
        GscDaily(site_url=SITE, date=date(2026, 10, 1), clicks=999, impressions=9999, position=1.0),
    ])
    await db_session.flush()

    seo = await gsc_service.month_summary(db_session, SITE, date(2026, 9, 1), date(2026, 9, 30))

    assert seo["status"] == "ok"
    assert seo["month"] == {"start": "2026-09-01", "end": "2026-09-30", "days": 2, "clicks": 100,
                            "impressions": 1000, "ctr": 10.0, "position": 3.8}  # (2*900+20*100)/1000
    assert seo["previous"]["clicks"] == 80 and seo["previous"]["position"] == 5.0
    assert seo["vs_previous"] == {"clicks_pct": 25.0, "impressions_pct": 0.0, "ctr_delta": 2.0,
                                  "position_delta": 1.2}
    assert seo["year_ago"]["clicks"] == 50 and seo["vs_year_ago"]["clicks_pct"] == 100.0


async def test_collector_adds_seo_only_to_full_month_digests(db_session):
    await _connect(db_session)
    client = await _client(db_session, "sc-domain:ejemplo.com")
    await _imported(db_session, last_data_date=date(2026, 10, 15))
    db_session.add(GscDaily(site_url=SITE, date=date(2026, 9, 3), clicks=12, impressions=300, position=7.0))
    await db_session.flush()

    monthly = await collect_digest_data(db_session, client.id, date(2026, 9, 1), date(2026, 9, 30))
    weekly = await collect_digest_data(db_session, client.id, date(2026, 9, 7), date(2026, 9, 13))
    again = await collect_digest_data(db_session, client.id, date(2026, 9, 1), date(2026, 9, 30))

    assert monthly["seo"]["status"] == "ok" and monthly["seo"]["month"]["clicks"] == 12
    assert "seo" not in weekly
    # La generación compara dos recolecciones: deben ser idénticas.
    assert again == monthly


async def test_status_endpoint_groups_clients_by_property(admin_client, db_session):
    await _connect(db_session)
    await _client(db_session, "https://ejemplo.com", name="Ejemplo")
    await _client(db_session, "https://ejemplo.com/", name="Ejemplo bis")
    await _client(db_session, None, name="Sin GSC")

    resp = await admin_client.get("/api/gsc/status")

    assert resp.status_code == 200
    body = resp.json()
    assert [c["google_email"] for c in body["connections"]] == ["seo@magnify.ing"]
    assert [s["site_url"] for s in body["sites"]] == ["https://ejemplo.com/"]
    assert sorted(c["name"] for c in body["sites"][0]["clients"]) == ["Ejemplo", "Ejemplo bis"]


async def test_only_admins_connect_or_import(member_client):
    for method, path in (("get", "/api/gsc/auth-url"), ("post", "/api/gsc/sync"),
                         ("post", "/api/gsc/connections/1/disconnect"), ("get", "/api/gsc/sites")):
        resp = await getattr(member_client, method)(path)
        assert resp.status_code == 403, path


# ── Varias cuentas de Google ─────────────────────────────────────────


async def test_each_property_is_imported_with_the_account_that_sees_it(db_session):
    agencia = await _connect(db_session, email="digital@magnify.ing", token="v1:agencia")
    david = await _connect(db_session, email="david@magnify.ing", token="v1:david")
    await _client(db_session, "sc-domain:a.com", name="A")
    await _client(db_session, "sc-domain:b.com", name="B")
    await _client(db_session, "sc-domain:nadie.com", name="Nadie")
    used = {}

    async def list_fn(token):
        if token == "v1:agencia":
            return [{"site_url": "sc-domain:a.com", "permission": "siteRestrictedUser"},
                    {"site_url": "sc-domain:b.com", "permission": "siteRestrictedUser"}]
        return [{"site_url": "sc-domain:b.com", "permission": "siteOwner"}]

    async def fetch(token, site, start, end):
        used[site] = token
        return _days(end, end)

    result = await gsc_service.sync_all(_session_factory(db_session), fetch=fetch, list_fn=list_fn,
                                        today=date(2026, 10, 18))

    assert result == {"status": "ok", "synced": 2, "failed": 1}
    # b.com la ven las dos: gana la de más permiso.
    assert used == {"sc-domain:a.com": "v1:agencia", "sc-domain:b.com": "v1:david"}
    assert (await db_session.get(GscSiteSync, "sc-domain:a.com")).connection_id == agencia.id
    assert (await db_session.get(GscSiteSync, "sc-domain:b.com")).connection_id == david.id
    nadie = await db_session.get(GscSiteSync, "sc-domain:nadie.com")
    assert nadie.error_code == "no_access" and nadie.connection_id is None


async def test_a_revoked_account_does_not_stop_the_others(db_session):
    caida = await _connect(db_session, email="vieja@magnify.ing", token="v1:vieja")
    await _connect(db_session, email="digital@magnify.ing", token="v1:buena")
    await _client(db_session, SITE)

    async def list_fn(token):
        if token == "v1:vieja":
            raise GscAuthError("invalid_grant")
        return [{"site_url": SITE, "permission": "siteFullUser"}]

    async def fetch(token, site, start, end):
        return _days(end, end)

    result = await gsc_service.sync_all(_session_factory(db_session), fetch=fetch, list_fn=list_fn,
                                        today=date(2026, 10, 18))

    assert result == {"status": "reconnect_required", "synced": 1, "failed": 0}
    assert (await db_session.get(GscConnection, caida.id)).status == "reconnect_required"
    assert (await db_session.get(GscSiteSync, SITE)).backfilled_at is not None


async def test_connecting_the_same_google_account_again_renews_it(db_session):
    first = await gsc_service.save_connection(db_session, refresh_token="uno", email="Digital@Magnify.ing", user_id=None)
    again = await gsc_service.save_connection(db_session, refresh_token="dos", email="digital@magnify.ing", user_id=None)
    other = await gsc_service.save_connection(db_session, refresh_token="tres", email="david@magnify.ing", user_id=None)

    assert first.id == again.id != other.id
    assert (await db_session.scalar(select(func.count()).select_from(GscConnection))) == 2
    assert again.google_email == "digital@magnify.ing"


async def test_disconnecting_one_account_keeps_the_rest(admin_client, db_session):
    a = (await _connect(db_session, email="a@magnify.ing")).id
    b = (await _connect(db_session, email="b@magnify.ing")).id
    await db_session.commit()

    resp = await admin_client.post(f"/api/gsc/connections/{a}/disconnect")

    assert resp.status_code == 200
    db_session.expire_all()
    assert await db_session.get(GscConnection, a) is None
    assert await db_session.get(GscConnection, b) is not None
    assert (await admin_client.post("/api/gsc/connections/999/disconnect")).status_code == 404

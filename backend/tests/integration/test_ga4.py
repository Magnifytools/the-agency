"""GA4 propio contra Postgres real: importación por cuenta, ficha, resumen mensual y su bloque."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.db.models import Client, ClientStatus, Ga4Daily, Ga4PropertySync, GscConnection
from backend.schemas.digest import DigestContent
from backend.services import ga4_service
from backend.services.client_status import Viewer, portfolio
from backend.services.digest_collector import collect_digest_data
from backend.services.digest_renderer import render_email, render_email_plain
from backend.services.ga4_service import Ga4Error, Ga4Row, aggregate_rows, is_ai_source, normalize_property

pytestmark = pytest.mark.integration
NOTHING = Viewer(is_admin=False, tasks=False, digests=False, timesheet=False)


def _factory(db):
    @asynccontextmanager
    async def factory():
        yield db
    return factory


async def _connect(db, email="digital@magnify.ing", token="v1:a"):
    c = GscConnection(google_email=email, refresh_token=token, status="connected", connected_at=datetime.now(UTC))
    db.add(c)
    await db.flush()
    return c


async def _client(db, prop="123456", name="Fit"):
    c = Client(name=name, status=ClientStatus.active, ga4_property_id=prop)
    db.add(c)
    await db.flush()
    return c


def test_property_ids_and_ai_sources_are_normalized():
    assert normalize_property("properties/123456") == "123456"
    assert normalize_property(" 123456 ") == "123456"
    assert normalize_property("G-ABC123") is None
    assert is_ai_source("chatgpt.com") and is_ai_source("www.perplexity.ai") and is_ai_source("gemini.google.com")
    assert not is_ai_source("google") and not is_ai_source("notchatgpt.com.evil.net")


def test_rows_add_up_per_day_and_split_ai():
    def row(day, source, sessions, events):
        return {"dimensionValues": [{"value": day}, {"value": source}],
                "metricValues": [{"value": str(sessions)}, {"value": str(events)}]}
    out = aggregate_rows([row("20261001", "google", 100, 3), row("20261001", "chatgpt.com", 10, 1.5),
                          row("20261002", "(direct)", 50, 0)])
    assert out == [Ga4Row(date(2026, 10, 1), 110, 4.5, 10, 1.5), Ga4Row(date(2026, 10, 2), 50, 0.0, 0, 0.0)]


async def test_sync_uses_the_account_that_sees_each_property(db_session):
    a = await _connect(db_session, "digital@magnify.ing", "v1:a")
    b = await _connect(db_session, "david@magnify.ing", "v1:b")
    await _client(db_session, "311111111", "Uno")
    await _client(db_session, "properties/322222222", "Dos")
    await _client(db_session, "333333333", "Nadie")
    used = {}

    async def list_fn(token):
        return ["311111111"] if token == "v1:a" else ["322222222"]

    async def fetch(token, pid, start, end):
        used[pid] = (token, start, end)
        return [Ga4Row(end, 10, 1.0, 2, 0.5)]

    result = await ga4_service.sync_all(_factory(db_session), fetch=fetch, list_fn=list_fn, today=date(2026, 10, 20))

    assert result == {"status": "ok", "synced": 2, "failed": 1, "leads_failed": 0}
    assert used["311111111"][0] == "v1:a" and used["322222222"][0] == "v1:b"
    # Primera vez: 16 meses hacia atrás hasta ayer.
    assert used["311111111"][2] == date(2026, 10, 19) and used["311111111"][1] == date(2026, 10, 19) - timedelta(days=486)
    assert (await db_session.get(Ga4PropertySync, "311111111")).connection_id == a.id
    assert (await db_session.get(Ga4PropertySync, "322222222")).connection_id == b.id
    assert (await db_session.get(Ga4PropertySync, "333333333")).error_code == "no_access"
    assert (await db_session.get(Ga4Daily, ("311111111", date(2026, 10, 19)))).ai_sessions == 2


async def test_account_without_analytics_permission_is_not_marked_for_reconnect(db_session):
    connection = await _connect(db_session)
    await _client(db_session, "311111111")

    async def list_fn(_token):
        raise Ga4Error("missing_scope")

    result = await ga4_service.sync_all(_factory(db_session), fetch=None, list_fn=list_fn, today=date(2026, 10, 20))

    assert result["failed"] == 1
    assert (await db_session.get(Ga4PropertySync, "311111111")).error_code == "missing_scope"
    assert (await db_session.get(GscConnection, connection.id)).status == "connected"


async def _imported(db, pid, *, until, synced_on):
    db.add(Ga4PropertySync(property_id=pid, backfilled_at=datetime.now(UTC), last_data_date=until,
                           last_synced_at=datetime.combine(synced_on, datetime.min.time(), UTC)))
    await db.flush()


async def test_month_summary_waits_for_google_to_settle_the_month(db_session):
    sept = (date(2026, 9, 1), date(2026, 9, 30))
    assert (await ga4_service.month_summary(db_session, None, *sept))["status"] == "no_property"
    assert (await ga4_service.month_summary(db_session, "311111111", *sept))["status"] == "not_synced"
    await _imported(db_session, "311111111", until=date(2026, 10, 1), synced_on=date(2026, 10, 2))
    assert (await ga4_service.month_summary(db_session, "311111111", *sept))["status"] == "incomplete"


async def test_month_summary_and_the_digest_block(db_session):
    client = await _client(db_session, "311111111")
    await _imported(db_session, "311111111", until=date(2026, 10, 18), synced_on=date(2026, 10, 19))
    db_session.add_all([
        Ga4Daily(property_id="311111111", date=date(2026, 9, 1), sessions=1000, key_events=20, ai_sessions=40, ai_key_events=2),
        Ga4Daily(property_id="311111111", date=date(2026, 9, 2), sessions=234, key_events=5, ai_sessions=10, ai_key_events=1),
        Ga4Daily(property_id="311111111", date=date(2026, 8, 5), sessions=1000, key_events=20, ai_sessions=25, ai_key_events=0),
    ])
    await db_session.flush()

    monthly = await collect_digest_data(db_session, client.id, date(2026, 9, 1), date(2026, 9, 30))
    weekly = await collect_digest_data(db_session, client.id, date(2026, 9, 7), date(2026, 9, 13))
    ga4 = monthly["ga4"]
    assert ga4["status"] == "ok"
    assert ga4["month"]["sessions"] == 1234 and ga4["month"]["key_events"] == 25.0 and ga4["month"]["ai_sessions"] == 50
    assert ga4["vs_previous"] == {"sessions_pct": 23.4, "key_events_pct": 25.0, "ai_sessions_pct": 100.0}
    assert "ga4" not in weekly

    content = DigestContent()
    plain = render_email_plain(content, ga4=ga4)
    assert "Visitas y conversiones · septiembre de 2026" in plain
    assert "1.234 visitas y 25 conversiones" in plain and "50 visitas llegaron desde asistentes de IA" in plain
    assert "Visitas y conversiones" in render_email(content, ga4=ga4)
    assert "Visitas y conversiones" not in render_email_plain(DigestContent(include_ga4=False), ga4=ga4)


async def test_the_record_shows_the_last_28_days(db_session):
    client = await _client(db_session, "311111111")
    await _imported(db_session, "311111111", until=date(2026, 10, 18), synced_on=date(2026, 10, 19))
    db_session.add_all([
        Ga4Daily(property_id="311111111", date=date(2026, 10, 18), sessions=300, key_events=6, ai_sessions=12, ai_key_events=1),
        Ga4Daily(property_id="311111111", date=date(2026, 9, 10), sessions=200, key_events=4, ai_sessions=6, ai_key_events=0),
    ])
    await db_session.flush()

    row = (await portfolio(db_session, [client], NOTHING))[0]

    assert row["ga4"]["current"]["sessions"] == 300 and row["ga4"]["previous"]["sessions"] == 200
    assert row["ga4"]["vs_previous"]["key_events_pct"] == 50.0
    # Sólo se enseña: no cambia el estado.
    assert row["status"] == "no_data"


async def test_status_lists_properties_with_their_account(admin_client, db_session):
    connection = await _connect(db_session)
    await _client(db_session, "properties/311111111", "Fit")
    db_session.add(Ga4PropertySync(property_id="311111111", connection_id=connection.id, error_code=None,
                                   last_data_date=date(2026, 10, 18)))
    await db_session.commit()

    body = (await admin_client.get("/api/ga4/status")).json()

    assert body["properties"] == [{
        "property_id": "311111111", "clients": [{"id": body["properties"][0]["clients"][0]["id"], "name": "Fit"}],
        "last_data_date": "2026-10-18", "last_synced_at": None, "error_code": None,
        "google_email": "digital@magnify.ing",
    }]

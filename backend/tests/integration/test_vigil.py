"""Integración con Vigil contra Postgres real: copia, estado del cliente y enlace."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from backend.config import settings
from backend.db.models import Client, ClientStatus, VigilSummary
from backend.services import vigil_service
from backend.services.client_status import Viewer, portfolio

pytestmark = pytest.mark.integration

NOTHING = Viewer(is_admin=False, tasks=False, digests=False, timesheet=False)


def _summary(slug, *, critical=0, warning=0, name=None):
    return {
        "slug": slug, "name": name or slug.title(), "watches_active": 12, "watches_with_error": 1,
        "last_checked_at": "2026-10-20T04:32:00+00:00",
        "changes_unacknowledged": {"critical": critical, "warning": warning, "info": 0},
        "changes_recent": {"critical": critical, "warning": warning, "info": 3},
        "last_run": {"status": "done", "started_at": "2026-10-20T04:30:00+00:00",
                     "finished_at": "2026-10-20T04:33:00+00:00", "changes_found": 2},
    }


@pytest.fixture
def vigil_settings(monkeypatch):
    monkeypatch.setattr(settings, "VIGIL_API_URL", "https://vigil.test")
    monkeypatch.setattr(settings, "VIGIL_SERVICE_KEY", "clave")


class _Factory:
    """async_session de mentira que devuelve la sesión del test (sin cerrarla)."""

    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


async def test_sync_upserts_and_drops_clients_vigil_no_longer_sends(db_session, vigil_settings):
    seen = {}

    def handler(request: httpx.Request):
        seen["key"] = request.headers.get("X-Service-Key")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"days": 7, "clients": seen.pop("payload")})

    db_session.add(VigilSummary(slug="antiguo", data=_summary("antiguo"), fetched_at=datetime.now(UTC)))
    await db_session.flush()
    seen["payload"] = [_summary("fit-generation", critical=1)]
    n = await vigil_service.sync(_Factory(db_session), transport=httpx.MockTransport(handler))

    assert n == 1
    assert seen["key"] == "clave" and seen["url"] == "https://vigil.test/api/integrations/summary?days=7"
    rows = (await db_session.scalars(select(VigilSummary))).all()
    assert [r.slug for r in rows] == ["fit-generation"]
    assert rows[0].data["changes_unacknowledged"]["critical"] == 1


async def test_a_failed_call_keeps_the_last_summary(db_session, vigil_settings):
    db_session.add(VigilSummary(slug="fit-generation", data=_summary("fit-generation"), fetched_at=datetime.now(UTC)))
    await db_session.flush()
    with pytest.raises(httpx.HTTPStatusError):
        await vigil_service.sync(_Factory(db_session), transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    assert await db_session.get(VigilSummary, "fit-generation") is not None


async def _client_with_summary(db, *, critical, fetched_at=None):
    client = Client(name="Fit Generation", status=ClientStatus.active, vigil_slug="fit-generation")
    db.add(client)
    db.add(VigilSummary(slug="fit-generation", data=_summary("fit-generation", critical=critical, warning=2),
                        fetched_at=fetched_at or datetime.now(UTC)))
    await db.flush()
    return client


async def test_critical_unreviewed_change_asks_to_watch(db_session):
    client = await _client_with_summary(db_session, critical=2)
    row = (await portfolio(db_session, [client], NOTHING))[0]
    assert row["status"] == "watch"
    assert row["reasons"] == ["2 cambios críticos en la web sin revisar (Vigil)"]
    assert row["vigil"]["critical"] == 2 and row["vigil"]["warning"] == 2
    assert row["vigil"]["url"] == settings.VIGIL_FRONTEND_URL


async def test_no_critical_change_is_a_measured_ok(db_session):
    client = await _client_with_summary(db_session, critical=0)
    row = (await portfolio(db_session, [client], NOTHING))[0]
    assert row["status"] == "ok" and row["reasons"] == []


async def test_a_stale_summary_is_shown_but_does_not_count(db_session):
    client = await _client_with_summary(db_session, critical=3, fetched_at=datetime.now(UTC) - timedelta(days=3))
    row = (await portfolio(db_session, [client], NOTHING))[0]
    assert row["vigil"]["fresh"] is False and row["vigil"]["critical"] == 3
    assert row["status"] == "no_data"


async def test_without_slug_there_is_no_vigil_block(db_session):
    client = Client(name="Sin Vigil", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    row = (await portfolio(db_session, [client], NOTHING))[0]
    assert row["vigil"] is None and row["status"] == "no_data"


async def test_linking_normalizes_and_rejects_duplicates_and_bad_slugs(admin_client, db_session):
    a = Client(name="A", status=ClientStatus.active)
    b = Client(name="B", status=ClientStatus.active)
    db_session.add_all([a, b])
    await db_session.commit()

    ok = await admin_client.put(f"/api/clients/{a.id}", json={"vigil_slug": "  Fit-Generation "})
    assert ok.status_code == 200, ok.text
    assert ok.json()["vigil_slug"] == "fit-generation"
    dup = await admin_client.put(f"/api/clients/{b.id}", json={"vigil_slug": "fit-generation"})
    assert dup.status_code == 409
    bad = await admin_client.put(f"/api/clients/{b.id}", json={"vigil_slug": "fit generation"})
    assert bad.status_code == 422
    cleared = await admin_client.put(f"/api/clients/{a.id}", json={"vigil_slug": ""})
    assert cleared.json()["vigil_slug"] is None


async def test_vigil_clients_lists_the_summary_with_its_link(admin_client, db_session):
    db_session.add(Client(name="Fit Generation", status=ClientStatus.active, vigil_slug="fit-generation"))
    db_session.add(VigilSummary(slug="fit-generation", data=_summary("fit-generation", name="Fit Generation"),
                                fetched_at=datetime.now(UTC)))
    await db_session.commit()
    r = await admin_client.get("/api/vigil/clients")
    assert r.status_code == 200
    assert r.json()["clients"] == [{"slug": "fit-generation", "name": "Fit Generation", "linked_to": "Fit Generation"}]

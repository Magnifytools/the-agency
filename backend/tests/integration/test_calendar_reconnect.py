"""Own local PostgreSQL only; all Google/provider calls are replaced by fakes."""
import asyncio
from datetime import datetime

import httpx
import pytest
from google.auth.exceptions import RefreshError

from backend.api.routes import google_calendar as route
from backend.db.models import User, Event, EventType
from backend.services import google_calendar_service as provider
from backend.tests.integration.test_scheduled_communications import fixture, client  # noqa: F401


async def connected(fixture):
    maker, ids, now = fixture
    async with maker() as db:
        user = await db.get(User, ids["member"])
        user.google_refresh_token = "synthetic-retained-grant"
        user.google_calendar_id = "primary"
        user.google_calendar_synced_at = now[0]
        event = Event(user_id=user.id, title="Saved meeting", event_type=EventType.meeting,
                      source="google", source_calendar_id="primary", google_event_id="saved",
                      start_time=datetime(2026, 9, 14, 10, 25))
        db.add(event)
        await db.commit()
        return event.id


async def test_invalid_grant_is_durable_actionable_private_and_user_scoped(fixture, monkeypatch, caplog):
    maker, ids, now = fixture
    event_id = await connected(fixture)
    secret = "sentinel-provider-token-never-expose"
    def revoked(*args, **kwargs):
        raise RefreshError(secret, {"error": "invalid_grant", "error_description": secret})
    monkeypatch.setattr(route, "fetch_events", revoked)
    async with client(fixture) as http:
        response = await http.post("/api/calendar/sync")
        assert response.status_code == 409
        assert "Reconecta" in response.json()["detail"]
        status = (await http.get("/api/calendar/status")).json()
        assert status["connected"] is False and status["connection_status"] == "reconnect_required"
        assert status["last_synced_at"] == "2026-09-14T08:00:00Z"
        assert secret not in response.text + str(status) + caplog.text
        assert "synthetic-retained-grant" not in str(status)
    async with maker() as db:
        user = await db.get(User, ids["member"])
        assert user.google_refresh_token == "synthetic-retained-grant"
        assert user.google_calendar_id == "primary" and user.google_calendar_synced_at == now[0]
        assert await db.get(Event, event_id) is not None
        assert (await db.get(User, ids["admin"])).google_calendar_connected is True
    # Neither manual retry nor worker calls the provider again for this credential.
    monkeypatch.setattr(route, "fetch_events", lambda *a, **k: pytest.fail("revoked credential retried"))
    async with client(fixture) as http:
        assert (await http.post("/api/calendar/sync")).status_code == 409
    async with maker() as db:
        assert await route.sync_user_events(db, await db.get(User, ids["member"])) == 0


@pytest.mark.parametrize("failure", [
    RuntimeError("invalid_grant text is not an authorization diagnosis"),
    RefreshError("invalid_grant text only"),
    RefreshError("unavailable", {"error": "temporarily_unavailable"}, retryable=True),
    TimeoutError("network"),
])
async def test_transient_or_unstructured_failure_preserves_connection(fixture, monkeypatch, failure):
    maker, ids, now = fixture
    event_id = await connected(fixture)
    def fail(*a, **k): raise failure
    monkeypatch.setattr(route, "fetch_events", fail)
    async with client(fixture) as http:
        assert (await http.post("/api/calendar/sync")).status_code == 502
        assert (await http.get("/api/calendar/status")).json()["connection_status"] == "connected"
    async with maker() as db:
        user = await db.get(User, ids["member"])
        assert user.google_refresh_token == "synthetic-retained-grant" and user.google_calendar_synced_at == now[0]
        assert await db.get(Event, event_id) is not None


async def test_successful_callback_recovers_revoked_connection_without_clearing_events(fixture, monkeypatch):
    maker, ids, _ = fixture
    event_id = await connected(fixture)
    async with maker() as db:
        user = await db.get(User, ids["member"]); user.google_calendar_connected = False
        await db.commit()
    monkeypatch.setattr(route, "exchange_code", lambda code: {"refresh_token": "fresh-synthetic-grant"})
    async with client(fixture) as http:
        response = await http.get("/api/calendar/callback", params={"code":"synthetic-code", "state":route._sign_oauth_state(ids["member"])})
        assert response.status_code == 307 and response.headers["location"] == "/settings?calendar=connected"
        status = (await http.get("/api/calendar/status")).json()
        assert status["connection_status"] == "connected" and status["last_synced_at"] is None
    async with maker() as db:
        user = await db.get(User, ids["member"])
        assert user.google_refresh_token.startswith("v1:")
        assert provider.decrypt_vault_secret(user.google_refresh_token) == "fresh-synthetic-grant"
        assert await db.get(Event, event_id) is not None


async def test_stale_invalid_grant_cannot_disable_a_new_callback(fixture, monkeypatch):
    maker, ids, _ = fixture
    await connected(fixture)
    reached, release = asyncio.Event(), asyncio.Event()
    async def delayed_fetch(func, *args):
        if func is route.exchange_code:
            return {"refresh_token": "newer-synthetic-grant"}
        reached.set()
        await release.wait()
        raise RefreshError("revoked", {"error": "invalid_grant"})
    monkeypatch.setattr(route.anyio.to_thread, "run_sync", delayed_fetch)
    async with client(fixture) as http:
        syncing = asyncio.create_task(http.post("/api/calendar/sync"))
        await reached.wait()
        response = await http.get("/api/calendar/callback", params={"code":"new", "state":route._sign_oauth_state(ids["member"])})
        assert response.status_code == 307
        release.set()
        assert (await syncing).status_code == 409
        status = (await http.get("/api/calendar/status")).json()
        assert status["connection_status"] == "connected"
    async with maker() as db:
        assert provider.decrypt_vault_secret((await db.get(User, ids["member"])).google_refresh_token) == "newer-synthetic-grant"


async def test_disconnect_distinguishes_removed_credentials_and_preserves_events(fixture):
    maker, ids, _ = fixture
    event_id = await connected(fixture)
    async with maker() as db:
        user = await db.get(User, ids["member"]); user.google_calendar_connected = False
        await db.commit()
    async with client(fixture) as http:
        assert (await http.post("/api/calendar/disconnect")).status_code == 200
        status = (await http.get("/api/calendar/status")).json()
        assert status["connection_status"] == "disconnected"
    async with maker() as db:
        assert (await db.get(User, ids["member"])).google_refresh_token is None
        assert await db.get(Event, event_id) is not None


async def test_connected_flag_without_credential_is_effectively_disconnected(
    fixture, monkeypatch
):
    maker, ids, _ = fixture
    async with maker() as db:
        user = await db.get(User, ids["member"])
        user.google_calendar_connected = True
        user.google_refresh_token = None
        await db.commit()
    monkeypatch.setattr(
        route,
        "fetch_events",
        lambda *args, **kwargs: pytest.fail("missing credential reached provider"),
    )

    async with client(fixture) as http:
        status = (await http.get("/api/calendar/status")).json()
        assert status["connected"] is False
        assert status["connection_status"] == "disconnected"
        response = await http.post("/api/calendar/sync")
        assert response.status_code == 400
        assert response.json()["detail"] == "Google Calendar no conectado"


async def test_callback_requires_valid_state_and_active_user(fixture, monkeypatch):
    maker, ids, _ = fixture
    await connected(fixture)
    monkeypatch.setattr(route, "exchange_code", lambda code: {"refresh_token":"should-not-store"})
    async with client(fixture) as http:
        assert "invalid_state" in (await http.get("/api/calendar/callback", params={"code":"x", "state":"forged"})).headers["location"]
        assert "invalid_state" in (await http.get("/api/calendar/callback", params={"error":"access_denied", "state":"forged"})).headers["location"]
        async with maker() as db:
            user = await db.get(User, ids["member"]); user.is_active = False
            await db.commit()
        response = await http.get("/api/calendar/callback", params={"code":"x", "state":route._sign_oauth_state(ids["member"])})
        assert response.headers["location"] == "/settings?calendar=error"
    async with maker() as db:
        assert (await db.get(User, ids["member"])).google_refresh_token == "synthetic-retained-grant"


@pytest.mark.parametrize(("callback", "location"), [
    ({"error": "access_denied", "error_description": "provider-private-cancellation"}, "/settings?calendar=cancelled"),
    ({"error": "temporarily_unavailable", "error_description": "provider-private-failure"}, "/settings?calendar=error"),
    ({}, "/settings?calendar=error"),
])
async def test_callback_without_code_preserves_saved_connection_after_signed_state(fixture, monkeypatch, callback, location):
    maker, ids, now = fixture
    event_id = await connected(fixture)
    exchanges = []
    monkeypatch.setattr(route, "exchange_code", lambda code: exchanges.append(code))
    params = {"state": route._sign_oauth_state(ids["member"]), **callback}
    async with client(fixture) as http:
        response = await http.get("/api/calendar/callback", params=params)
    assert response.status_code == 307 and response.headers["location"] == location
    assert "provider-private" not in response.text + response.headers["location"]
    assert exchanges == []
    async with maker() as db:
        user = await db.get(User, ids["member"])
        assert user.google_refresh_token == "synthetic-retained-grant"
        assert user.google_calendar_id == "primary" and user.google_calendar_synced_at == now[0]
        assert await db.get(Event, event_id) is not None


async def test_sync_and_status_require_authentication_and_active_identity(fixture, monkeypatch):
    from fastapi import FastAPI
    from backend.db.database import get_db
    from backend.core.security import create_access_token
    maker, ids, _ = fixture
    await connected(fixture)
    app = FastAPI(); app.include_router(route.router)
    async def session():
        async with maker() as db: yield db
    app.dependency_overrides[get_db] = session
    monkeypatch.setattr(route, "fetch_events", lambda *a, **k: pytest.fail("unauthorized provider call"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/api/calendar/status")).status_code == 401
        assert (await http.post("/api/calendar/sync")).status_code == 401
        async with maker() as db:
            user = await db.get(User, ids["member"]); user.is_active = False
            await db.commit()
        token = create_access_token({"sub": str(ids["member"])})
        assert (await http.post("/api/calendar/sync", headers={"Authorization": f"Bearer {token}"})).status_code == 403


async def test_callback_failure_does_not_log_error_details_or_remove_saved_state(fixture, monkeypatch, caplog):
    maker, ids, _ = fixture
    event_id = await connected(fixture)
    secret = "sentinel-oauth-private-response"
    def fail(code): raise RefreshError(secret, {"error": "invalid_grant", "error_description": secret})
    monkeypatch.setattr(route, "exchange_code", fail)
    async with client(fixture) as http:
        response = await http.get("/api/calendar/callback", params={"code":"expired", "state":route._sign_oauth_state(ids["member"])})
        assert response.headers["location"] == "/settings?calendar=error"
    assert secret not in caplog.text
    async with maker() as db:
        assert (await db.get(User, ids["member"])).google_refresh_token == "synthetic-retained-grant"
        assert await db.get(Event, event_id) is not None

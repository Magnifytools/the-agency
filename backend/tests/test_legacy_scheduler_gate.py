"""B2 replacement for bridge tests: old producers have been removed permanently."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException
from backend.config import Settings, settings
from backend.startup import background_tasks
from backend.api.routes import google_calendar


def test_new_scheduler_requires_explicit_enablement():
    assert Settings.model_fields["SCHEDULED_COMMUNICATIONS_ENABLED"].default is False


@pytest.mark.parametrize("enabled", [True, False])
def test_only_new_scheduler_and_calendar_sync_can_start(monkeypatch, enabled):
    names = []
    def capture(coroutine, *, name):
        names.append(name); coroutine.close()
        return SimpleNamespace(add_done_callback=lambda _: None)
    monkeypatch.setattr(background_tasks.asyncio, "create_task", capture)
    monkeypatch.setattr(settings, "SCHEDULED_COMMUNICATIONS_ENABLED", enabled)
    monkeypatch.setattr(settings, "DELIVERY_WORKER_ENABLED", True)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "synthetic")
    background_tasks.start_background_tasks()
    assert not {"daily-reminders", "weekly-report", "meeting-alerts"}.intersection(names)
    assert ("scheduled-communications" in names) is enabled
    assert ("calendar-sync" in names) is enabled
    assert "manual-deliveries" in names


async def test_paused_sync_does_not_query_provider_and_old_extension_always_stops(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULED_COMMUNICATIONS_ENABLED", False)
    db = AsyncMock()
    user = SimpleNamespace(google_calendar_connected=True, google_refresh_token="synthetic")
    with pytest.raises(HTTPException) as error: await google_calendar.trigger_sync(db, user)
    assert error.value.status_code == 409
    assert await google_calendar.upcoming_meetings(60, db, user) == []
    db.execute.assert_not_called()


async def test_oauth_preserves_connection_without_enabling_reminders(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULED_COMMUNICATIONS_ENABLED", False)
    monkeypatch.setattr(google_calendar, "exchange_code", lambda _: {"refresh_token": "synthetic"})
    user = SimpleNamespace(id=77, preferences={}, is_active=True)
    result = MagicMock(); result.scalar_one_or_none.return_value = user
    db = AsyncMock(); db.execute.return_value = result
    response = await google_calendar.calendar_callback("code", google_calendar._sign_oauth_state(77), db)
    assert response.headers["location"] == "/settings?calendar=connected"
    assert user.google_calendar_connected is True and user.preferences == {}
    db.commit.assert_awaited_once()


async def test_first_calendar_sync_precedes_initial_sleep(monkeypatch):
    from contextlib import asynccontextmanager
    from backend.db import database
    calls = []
    user = SimpleNamespace(id=7, full_name="Person", short_name="Person", email="person@example.test")
    result = MagicMock(); result.all.return_value = [user.id]
    statements = []
    async def scalars(statement):
        statements.append(statement)
        return result
    db = AsyncMock(); db.scalars.side_effect = scalars; db.get.return_value = user
    @asynccontextmanager
    async def session(): yield db
    async def sync(*args): calls.append("sync"); return 1
    async def sleep(seconds):
        calls.append("sleep")
        raise KeyboardInterrupt("stop loop")
    monkeypatch.setattr(database, "async_session", session)
    monkeypatch.setattr(google_calendar, "sync_user_events", sync)
    monkeypatch.setattr(background_tasks.asyncio, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt): await background_tasks._calendar_sync_loop()
    assert calls == ["sync", "sleep"]
    assert "users.google_refresh_token IS NOT NULL" in str(statements[0])

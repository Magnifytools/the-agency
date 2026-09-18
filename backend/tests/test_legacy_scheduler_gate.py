"""Pure rollout-bridge tests. No task runs, database connection or provider call."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from backend.config import Settings, settings
from backend.startup import background_tasks
from backend.api.routes import google_calendar


def test_legacy_default_preserves_current_behavior():
    assert Settings.model_fields["LEGACY_SCHEDULED_COMMUNICATIONS_ENABLED"].default is True


@pytest.mark.parametrize("enabled", [True, False])
def test_gate_controls_only_legacy_producers_at_startup(monkeypatch, enabled):
    names = []
    def capture(coroutine, *, name):
        names.append(name)
        coroutine.close()  # never execute loops
        return SimpleNamespace(add_done_callback=lambda _: None)
    monkeypatch.setattr(background_tasks.asyncio, "create_task", capture)
    monkeypatch.setattr(settings, "LEGACY_SCHEDULED_COMMUNICATIONS_ENABLED", enabled)
    monkeypatch.setattr(settings, "DELIVERY_WORKER_ENABLED", True)
    monkeypatch.setattr(settings, "DISCORD_OWNER_USER_ID", "123456789")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "synthetic-client")
    background_tasks.start_background_tasks()
    legacy = {"daily-reminders", "weekly-report", "calendar-sync", "meeting-alerts"}
    assert legacy.intersection(names) == (legacy if enabled else set())
    assert {"manual-deliveries", "recurring-gen", "retention-cleanup"} <= set(names)


async def test_sync_and_old_extension_pause_before_database_or_network(monkeypatch):
    monkeypatch.setattr(settings, "LEGACY_SCHEDULED_COMMUNICATIONS_ENABLED", False)
    fetch = MagicMock(side_effect=AssertionError("No provider call"))
    monkeypatch.setattr(google_calendar, "fetch_events", fetch)
    db = AsyncMock()
    user = SimpleNamespace(google_calendar_connected=True, google_refresh_token="synthetic")
    with pytest.raises(HTTPException) as error:
        await google_calendar.trigger_sync(db, user)
    assert error.value.status_code == 409 and "conexión" in error.value.detail
    assert await google_calendar.upcoming_meetings(60, db, user) == []
    db.execute.assert_not_called(); fetch.assert_not_called()


async def test_paused_sync_does_not_break_successful_oauth_connection(monkeypatch):
    monkeypatch.setattr(settings, "LEGACY_SCHEDULED_COMMUNICATIONS_ENABLED", False)
    monkeypatch.setattr(google_calendar, "exchange_code", lambda code: {"refresh_token": "synthetic-refresh"})
    sync = AsyncMock(side_effect=AssertionError("OAuth must not sync"))
    monkeypatch.setattr(google_calendar, "sync_user_events", sync)
    user = SimpleNamespace(id=77, preferences={})
    result = MagicMock(); result.scalar_one_or_none.return_value = user
    db = AsyncMock(); db.execute.return_value = result
    response = await google_calendar.calendar_callback("synthetic-code", google_calendar._sign_oauth_state(77), db)
    assert response.headers["location"] == "/settings?calendar=connected"
    assert user.google_calendar_connected is True and user.google_refresh_token.startswith("v1:")
    db.commit.assert_awaited_once(); sync.assert_not_called()

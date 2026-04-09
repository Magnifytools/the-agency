"""Tests for Google Calendar integration routes."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, date


@pytest.mark.asyncio
class TestCalendarStatus:
    async def test_status_returns_200(self, admin_client):
        resp = await admin_client.get("/api/calendar/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "connected" in data

    async def test_status_has_connected_field(self, admin_client):
        resp = await admin_client.get("/api/calendar/status")
        data = resp.json()
        assert isinstance(data["connected"], bool)


@pytest.mark.asyncio
class TestCalendarAuthUrl:
    async def test_auth_url_returns_url(self, admin_client):
        with patch("backend.api.routes.google_calendar.settings") as mock_settings:
            mock_settings.GOOGLE_CLIENT_ID = "test-client-id"
            mock_settings.GOOGLE_CLIENT_SECRET = "test-secret"
            mock_settings.GOOGLE_REDIRECT_URI = "http://localhost/callback"
            resp = await admin_client.get("/api/calendar/auth-url")
            assert resp.status_code == 200
            data = resp.json()
            assert "url" in data
            assert "accounts.google.com" in data["url"]


@pytest.mark.asyncio
class TestCalendarDisconnect:
    async def test_disconnect_returns_ok(self, admin_client):
        resp = await admin_client.post("/api/calendar/disconnect")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestCalendarUpcoming:
    async def test_upcoming_returns_list(self, admin_client):
        resp = await admin_client.get("/api/calendar/upcoming?minutes=60")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_upcoming_invalid_minutes(self, admin_client):
        resp = await admin_client.get("/api/calendar/upcoming?minutes=1")
        assert resp.status_code == 422




@pytest.mark.asyncio
class TestCalendarEvents:
    async def test_list_events_returns_list(self, admin_client):
        resp = await admin_client.get("/api/calendar/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

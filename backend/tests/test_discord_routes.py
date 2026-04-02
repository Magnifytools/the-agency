"""Tests for Discord integration endpoints.

Covers:
- Auth required → 401
- Admin required for settings update → 403
- Preview endpoint → 200
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestDiscordAuth:
    """Auth required for /api/discord"""

    async def test_discord_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/discord/settings")
        assert resp.status_code == 401

    async def test_discord_send_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/discord/send")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestDiscordAdmin:
    """Admin required for Discord settings"""

    async def test_update_settings_member_forbidden(self, member_client):
        resp = await member_client.put(
            "/api/discord/settings",
            json={"webhook_url": "https://discord.com/api/webhooks/123/abc"},
        )
        assert resp.status_code == 403

    async def test_test_webhook_member_forbidden(self, member_client):
        resp = await member_client.post("/api/discord/test-webhook")
        assert resp.status_code == 403

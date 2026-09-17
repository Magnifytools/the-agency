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
async def test_weekly_sender_builds_civil_overdue_query_without_real_transport(monkeypatch, admin_user):
    from datetime import date
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from backend.api.routes import discord

    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = result
    monkeypatch.setattr(discord, "_get_or_create_settings", AsyncMock(return_value=SimpleNamespace(bot_token="synthetic")))
    monkeypatch.setattr(discord, "_decrypt_field", lambda _: "synthetic-token")
    monkeypatch.setattr(discord.settings, "DISCORD_OWNER_USER_ID", "synthetic-recipient")
    transport = AsyncMock(return_value=True)
    monkeypatch.setattr(discord, "_send_discord_dm", transport)

    response = await discord.send_weekly_report(week_start="2026-09-14", db=db, current_user=admin_user)

    assert response.success is True
    transport.assert_awaited_once()
    assert "14/09 al 20/09/2026" in transport.await_args.args[2]
    overdue_query = db.execute.await_args_list[2].args[0]
    assert "CAST(tasks.due_date AS DATE)" in str(overdue_query)
    assert date(2026, 9, 14) in overdue_query.compile().params.values()


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

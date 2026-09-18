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
async def test_weekly_sender_passes_explicit_civil_period_to_shared_reader(monkeypatch, admin_user):
    from datetime import date
    from unittest.mock import AsyncMock
    from backend.api.routes import discord

    db = AsyncMock()
    generator = AsyncMock(return_value="Reviewed weekly report")
    enqueue = AsyncMock(return_value={"success": False, "status": "pending"})
    monkeypatch.setattr(discord, "generate_weekly_report", generator)
    monkeypatch.setattr(discord, "enqueue_request", enqueue)
    response = await discord.send_weekly_report(week_start=date(2026, 9, 14), db=db, current_user=admin_user)
    assert response["status"] == "pending" and response["success"] is False
    generator.assert_awaited_once_with(db, period_start=date(2026, 9, 14), period_end=date(2026, 9, 20))
    assert enqueue.await_args.kwargs["content"] == "Reviewed weekly report"


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


@pytest.mark.asyncio
class TestCustomContract:
    @pytest.mark.parametrize("intent", [None, "digest", "custom-v0"])
    async def test_cached_digest_rejected_before_settings_or_provider(self, admin_client, monkeypatch, intent):
        from unittest.mock import AsyncMock
        from backend.api.routes import discord

        settings_lookup = AsyncMock(side_effect=AssertionError("must not resolve destination"))
        provider = AsyncMock(side_effect=AssertionError("must not send"))
        monkeypatch.setattr(discord, "_get_or_create_settings", settings_lookup)
        monkeypatch.setattr(discord, "_send_discord_message", provider)
        response = await admin_client.post(
            "/api/discord/send-custom", json={"content": "Cached digest preview"},
            headers={"X-Agency-Send-Intent": intent} if intent else {},
        )
        assert response.status_code == 409
        assert "Recarga" in response.json()["detail"]
        settings_lookup.assert_not_awaited()
        provider.assert_not_awaited()

    async def test_current_custom_contract_stages_explicit_send(self, admin_client, monkeypatch):
        from unittest.mock import AsyncMock
        from backend.api.routes import discord
        receipt = dict(delivery_id="test", success=False, status="pending", message="En cola", source_kind="communication", source_id=1,
                       source_version="hash", source_changed=False, content="Explicit custom text", created_at="2026-09-17T00:00:00Z",
                       sent_at=None, error_code=None, steps=[], can_retry=False, can_resend=False, can_cancel=True, worker_enabled=False)
        enqueue = AsyncMock(return_value=receipt)
        monkeypatch.setattr(discord, "enqueue_request", enqueue)
        response = await admin_client.post("/api/discord/send-custom", json={"content": "Explicit custom text"},
                                           headers={"X-Agency-Send-Intent": "custom-v1"})
        assert response.status_code == 202 and response.json()["success"] is False
        assert enqueue.await_args.kwargs["content"] == "Explicit custom text"

    async def test_contract_header_does_not_grant_admin(self, member_client, monkeypatch):
        from unittest.mock import AsyncMock
        from backend.api.routes import discord

        provider = AsyncMock(side_effect=AssertionError("must not send"))
        monkeypatch.setattr(discord, "_send_discord_message", provider)
        response = await member_client.post(
            "/api/discord/send-custom", json={"content": "Unauthorized text"},
            headers={"X-Agency-Send-Intent": "custom-v1"},
        )
        assert response.status_code == 403
        provider.assert_not_awaited()

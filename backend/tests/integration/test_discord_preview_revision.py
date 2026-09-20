"""Reviewed daily text is the exact content staged, without provider calls."""
from datetime import date, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select

from backend.api.routes import discord
from backend.config import settings
from backend.db.models import CommunicationRequest, Delivery, TimeEntry

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def synthetic_destination(monkeypatch):
    monkeypatch.setattr(settings, "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/test-only")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(
        side_effect=AssertionError("Provider network is forbidden in preview tests"),
    ))


async def test_changed_hours_require_new_preview_before_staging(admin_client, admin_user, db_session):
    entry = TimeEntry(user_id=admin_user.id, minutes=31, date=datetime(2026, 9, 20, 10),
                      started_at=datetime(2026, 9, 20, 10))
    db_session.add(entry)
    await db_session.flush()
    preview = await admin_client.get("/api/discord/preview", params={"date": "2026-09-20"})
    assert preview.status_code == 200, preview.text
    initial = preview.json()
    assert "31m" in initial["summary"] and len(initial["revision"]) == 64

    entry.minutes = 47
    await db_session.flush()
    stale = await admin_client.post("/api/discord/send", params={
        "date": initial["date"], "expected_revision": initial["revision"],
    })
    assert stale.status_code == 409, stale.text
    assert await db_session.scalar(select(func.count()).select_from(CommunicationRequest)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Delivery)) == 0

    fresh = (await admin_client.get("/api/discord/preview", params={"date": "2026-09-20"})).json()
    assert fresh["revision"] != initial["revision"] and "47m" in fresh["summary"]
    send_params = {"date": fresh["date"], "expected_revision": fresh["revision"]}
    sent = await admin_client.post("/api/discord/send", params=send_params)
    assert sent.status_code == 202, sent.text
    receipt = sent.json()
    assert receipt["content"] == fresh["summary"]
    assert receipt["success"] is False and receipt["status"] == "pending"
    stored = await db_session.scalar(select(CommunicationRequest))
    assert stored.content == fresh["summary"]
    assert stored.period_start == stored.period_end == date(2026, 9, 20)
    repeated = await admin_client.post("/api/discord/send", params=send_params)
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["delivery_id"] == receipt["delivery_id"]
    assert await db_session.scalar(select(func.count()).select_from(CommunicationRequest)) == 1


async def test_default_date_uses_same_business_day_and_revision_binds_date(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(discord, "business_today", lambda: date(2026, 10, 25))
    preview = (await admin_client.get("/api/discord/preview")).json()
    assert preview["date"] == "2026-10-25"
    wrong_day = await admin_client.post("/api/discord/send", params={
        "date": "2026-10-26", "expected_revision": preview["revision"],
    })
    assert wrong_day.status_code == 409
    response = await admin_client.post("/api/discord/send", params={"expected_revision": preview["revision"]})
    assert response.status_code == 202, response.text
    assert response.json()["date"] == preview["date"]
    assert response.json()["content"] == preview["summary"]


@pytest.mark.parametrize("method,path,params", [
    ("GET", "/api/discord/preview", {"date": "2026-02-30"}),
    ("POST", "/api/discord/send", {"date": "not-a-date"}),
    ("POST", "/api/discord/send", {"expected_revision": "invalid"}),
])
async def test_invalid_review_contract_is_validation_error(admin_client, method, path, params):
    assert (await admin_client.request(method, path, params=params)).status_code == 422


async def test_member_cannot_preview_or_stage_team_summary(member_client, db_session):
    assert (await member_client.get("/api/discord/preview")).status_code == 403
    assert (await member_client.post("/api/discord/send")).status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(CommunicationRequest)) == 0

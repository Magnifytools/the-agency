"""Tests for PM intelligence routes."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestPmBriefing:
    async def test_daily_briefing_returns_200(self, admin_client):
        resp = await admin_client.get("/api/pm/daily-briefing")
        assert resp.status_code == 200

    async def test_insights_returns_200(self, admin_client):
        resp = await admin_client.get("/api/pm/insights")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_insights_count_returns_200(self, admin_client):
        resp = await admin_client.get("/api/pm/insights/count")
        assert resp.status_code == 200

"""Tests for dashboard endpoints.

Covers:
- Overview → 200
- Profitability → 200
- Team → 200
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestDashboardOverview:
    """GET /api/dashboard/overview"""

    async def test_overview_returns_200(self, admin_client):
        resp = await admin_client.get("/api/dashboard/overview")
        assert resp.status_code == 200

    async def test_overview_with_period(self, admin_client):
        resp = await admin_client.get(
            "/api/dashboard/overview",
            params={"year": 2025, "month": 6},
        )
        assert resp.status_code == 200

    async def test_overview_invalid_month(self, admin_client):
        resp = await admin_client.get(
            "/api/dashboard/overview",
            params={"month": 13},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestDashboardAuth:
    """Auth required for /api/dashboard"""

    async def test_overview_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/dashboard/overview")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestDashboardProfitability:
    """GET /api/dashboard/profitability"""

    async def test_profitability_returns_200(self, admin_client):
        resp = await admin_client.get("/api/dashboard/profitability")
        assert resp.status_code == 200

    async def test_profitability_with_period(self, admin_client):
        resp = await admin_client.get(
            "/api/dashboard/profitability",
            params={"year": 2025, "month": 3},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestDashboardTeam:
    """GET /api/dashboard/team"""

    async def test_team_returns_200(self, admin_client):
        resp = await admin_client.get("/api/dashboard/team")
        assert resp.status_code == 200

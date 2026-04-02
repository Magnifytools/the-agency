"""Tests for financial advisor endpoints.

Covers:
- Overview → 200
- Insights → 200
- Tasks → 200
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestAdvisorOverview:
    """GET /api/finance/advisor/overview"""

    async def test_overview_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/advisor/overview")
        assert resp.status_code == 200

    async def test_overview_with_period(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/advisor/overview",
            params={"year": 2025, "month": 6},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestAdvisorAuth:
    """Auth required for /api/finance/advisor"""

    async def test_overview_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/finance/advisor/overview")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestAdvisorInsights:
    """GET /api/finance/advisor/insights"""

    async def test_insights_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/advisor/insights")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestAdvisorTasks:
    """GET /api/finance/advisor/tasks"""

    async def test_tasks_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/advisor/tasks")
        assert resp.status_code == 200

    async def test_create_task_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/advisor/tasks", json={}
        )
        assert resp.status_code == 422

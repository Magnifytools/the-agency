"""Tests for growth ideas endpoints.

Covers:
- List growth ideas → 200
- Create growth idea validation → 422
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestGrowthList:
    """GET /api/growth"""

    async def test_list_growth_returns_200(self, admin_client):
        resp = await admin_client.get("/api/growth")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_growth_with_status_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/growth",
            params={"status": "idea", "limit": 10},
        )
        assert resp.status_code == 200

    async def test_list_growth_by_project(self, admin_client):
        resp = await admin_client.get(
            "/api/growth", params={"project_id": 1}
        )
        assert resp.status_code == 200

    async def test_list_growth_by_funnel_stage(self, admin_client):
        resp = await admin_client.get(
            "/api/growth", params={"funnel_stage": "acquisition"}
        )
        assert resp.status_code == 200

    async def test_list_growth_custom_pagination(self, admin_client):
        resp = await admin_client.get(
            "/api/growth", params={"limit": 5, "offset": 0}
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestGrowthAuth:
    """Auth required for /api/growth"""

    async def test_list_growth_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/growth")
        assert resp.status_code == 401

    async def test_create_growth_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/growth", json={})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestGrowthCreate:
    """POST /api/growth"""

    async def test_create_growth_missing_title_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/growth",
            json={"description": "No title"},
        )
        assert resp.status_code == 422

    async def test_create_growth_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/growth", json={})
        assert resp.status_code == 422

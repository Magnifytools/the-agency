"""Tests for report generation endpoints.

Covers:
- List reports → 200
- Generate report → validation
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestReportsList:
    """GET /api/reports"""

    async def test_list_reports_returns_200(self, admin_client):
        resp = await admin_client.get("/api/reports")
        assert resp.status_code == 200

    async def test_list_reports_with_type(self, admin_client):
        resp = await admin_client.get(
            "/api/reports", params={"type": "monthly"}
        )
        assert resp.status_code in (200, 422)


@pytest.mark.asyncio
class TestReportsAuth:
    """Auth required for /api/reports"""

    async def test_list_reports_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/reports")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestReportGenerate:
    """POST /api/reports/generate"""

    async def test_generate_report_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/reports/generate", json={})
        assert resp.status_code == 422

    async def test_generate_report_missing_type_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/reports/generate",
            json={"client_id": 1},
        )
        assert resp.status_code == 422

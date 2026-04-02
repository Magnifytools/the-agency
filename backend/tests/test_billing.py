"""Tests for billing endpoints.

Covers:
- Billing overdue → 200
- Billing export → 200
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestBillingOverdue:
    """GET /api/billing/overdue"""

    async def test_overdue_returns_200(self, admin_client):
        resp = await admin_client.get("/api/billing/overdue")
        assert resp.status_code == 200

    async def test_overdue_with_period(self, admin_client):
        resp = await admin_client.get(
            "/api/billing/overdue",
            params={"year": 2025, "month": 6},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestBillingAuth:
    """Auth required for /api/billing"""

    async def test_billing_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/billing/overdue")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestBillingExport:
    """GET /api/billing/export"""

    async def test_export_returns_200(self, admin_client):
        resp = await admin_client.get("/api/billing/export")
        assert resp.status_code == 200

    async def test_export_with_period(self, admin_client):
        resp = await admin_client.get(
            "/api/billing/export",
            params={"year": 2025, "month": 6},
        )
        assert resp.status_code == 200

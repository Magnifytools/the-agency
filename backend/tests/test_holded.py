"""Tests for Holded integration endpoints.

Covers:
- Config → 200
- Sync status → 200
- Auth required → 401
- Admin required for sync
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestHoldedAuth:
    """Auth required for /api/holded"""

    async def test_holded_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/holded/config")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestHoldedConfig:
    """GET /api/holded/config"""

    async def test_config_returns_200(self, admin_client):
        resp = await admin_client.get("/api/holded/config")
        assert resp.status_code == 200

    async def test_sync_status_returns_200(self, admin_client):
        resp = await admin_client.get("/api/holded/sync/status")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestHoldedInvoices:
    """GET /api/holded/invoices"""

    async def test_list_invoices_returns_200(self, admin_client):
        resp = await admin_client.get("/api/holded/invoices")
        assert resp.status_code == 200

    async def test_list_invoices_with_filters(self, admin_client):
        resp = await admin_client.get(
            "/api/holded/invoices",
            params={"page": 1, "page_size": 10},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestHoldedSync:
    """POST /api/holded/sync/* — admin only"""

    async def test_sync_contacts_member_forbidden(self, member_client):
        resp = await member_client.post("/api/holded/sync/contacts")
        assert resp.status_code == 403

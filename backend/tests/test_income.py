"""Tests for income tracking endpoints.

Covers:
- List income → 200
- Create income validation → 422
- Get income → 404
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestIncomeList:
    """GET /api/finance/income"""

    async def test_list_income_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/income")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_income_with_date_range(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/income",
            params={"date_from": "2025-01-01", "date_to": "2025-12-31", "limit": 10},
        )
        assert resp.status_code == 200

    async def test_list_income_by_client(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/income", params={"client_id": 1}
        )
        assert resp.status_code == 200

    async def test_list_income_by_type(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/income", params={"type": "factura"}
        )
        assert resp.status_code == 200

    async def test_list_income_by_status(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/income", params={"status": "cobrado"}
        )
        assert resp.status_code == 200

    async def test_list_income_custom_offset(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/income",
            params={"offset": 10, "limit": 5},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestIncomeAuth:
    """Auth required for /api/finance/income"""

    async def test_list_income_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/finance/income")
        assert resp.status_code == 401

    async def test_create_income_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/finance/income", json={})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestIncomeCreate:
    """POST /api/finance/income"""

    async def test_create_income_missing_fields_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/income",
            json={"description": "Missing amount and date"},
        )
        assert resp.status_code == 422

    async def test_create_income_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/finance/income", json={})
        assert resp.status_code == 422

    async def test_create_income_invalid_amount_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/income",
            json={"date": "2025-06-01", "description": "Test", "amount": -10},
        )
        assert resp.status_code == 422

    async def test_create_income_zero_amount_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/income",
            json={"date": "2025-06-01", "description": "Test", "amount": 0},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestIncomeDetail:
    """GET /api/finance/income/{id}"""

    async def test_get_income_not_found(self, admin_client):
        resp = await admin_client.get("/api/finance/income/99999")
        assert resp.status_code == 404

    async def test_get_income_invalid_id(self, admin_client):
        resp = await admin_client.get("/api/finance/income/abc")
        assert resp.status_code == 422

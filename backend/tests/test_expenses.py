"""Tests for expense tracking endpoints.

Covers:
- List expenses → 200
- Create expense validation → 422
- Get expense → 404
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestExpensesList:
    """GET /api/finance/expenses"""

    async def test_list_expenses_returns_200(self, admin_client):
        resp = await admin_client.get("/api/finance/expenses")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_expenses_with_date_range(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/expenses",
            params={"date_from": "2025-01-01", "date_to": "2025-12-31", "limit": 10},
        )
        assert resp.status_code == 200

    async def test_list_expenses_with_category(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/expenses",
            params={"category_id": 1},
        )
        assert resp.status_code == 200

    async def test_list_expenses_recurring_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/expenses",
            params={"is_recurring": True},
        )
        assert resp.status_code == 200

    async def test_list_expenses_custom_offset(self, admin_client):
        resp = await admin_client.get(
            "/api/finance/expenses",
            params={"offset": 10, "limit": 5},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestExpensesAuth:
    """Auth required for /api/finance/expenses"""

    async def test_list_expenses_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/finance/expenses")
        assert resp.status_code == 401

    async def test_create_expense_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/finance/expenses", json={})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestExpenseCreate:
    """POST /api/finance/expenses"""

    async def test_create_expense_missing_fields_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/expenses",
            json={"description": "Missing amount and date"},
        )
        assert resp.status_code == 422

    async def test_create_expense_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/finance/expenses", json={})
        assert resp.status_code == 422

    async def test_create_expense_invalid_amount_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/expenses",
            json={"date": "2025-06-01", "description": "Test", "amount": -10},
        )
        assert resp.status_code == 422

    async def test_create_expense_zero_amount_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/expenses",
            json={"date": "2025-06-01", "description": "Test", "amount": 0},
        )
        assert resp.status_code == 422

    async def test_create_expense_invalid_vat_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/expenses",
            json={"date": "2025-06-01", "description": "Test", "amount": 10, "vat_rate": 200},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestExpenseDetail:
    """GET /api/finance/expenses/{id}"""

    async def test_get_expense_not_found(self, admin_client):
        resp = await admin_client.get("/api/finance/expenses/99999")
        assert resp.status_code == 404

    async def test_get_expense_invalid_id(self, admin_client):
        resp = await admin_client.get("/api/finance/expenses/abc")
        assert resp.status_code == 422

"""Tests for client CRUD endpoints.

Covers:
- List clients → 200
- Create client validation → 422
- Get client → 404
- Auth required → 401
- Pagination
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestClientsList:
    """GET /api/clients"""

    async def test_list_clients_returns_200(self, admin_client):
        resp = await admin_client.get("/api/clients")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_list_clients_with_status_filter(self, admin_client):
        resp = await admin_client.get("/api/clients", params={"status": "active"})
        assert resp.status_code == 200

    async def test_list_clients_pagination(self, admin_client):
        resp = await admin_client.get(
            "/api/clients", params={"page": 1, "page_size": 10}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_list_clients_invalid_page_size(self, admin_client):
        resp = await admin_client.get(
            "/api/clients", params={"page_size": 0}
        )
        assert resp.status_code == 422

    async def test_list_clients_invalid_page(self, admin_client):
        resp = await admin_client.get(
            "/api/clients", params={"page": 0}
        )
        assert resp.status_code == 422

    async def test_list_clients_finished_status(self, admin_client):
        resp = await admin_client.get("/api/clients", params={"status": "finished"})
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestClientsAuth:
    """Auth required for /api/clients"""

    async def test_list_clients_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/clients")
        assert resp.status_code == 401

    async def test_create_client_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/clients", json={"name": "Test"})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestClientCreate:
    """POST /api/clients"""

    async def test_create_client_missing_name_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/clients",
            json={"email": "test@test.com"},
        )
        assert resp.status_code == 422

    async def test_create_client_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/clients", json={})
        assert resp.status_code == 422

    async def test_create_client_negative_budget_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/clients",
            json={"name": "Test Client", "monthly_budget": -100},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestClientDetail:
    """GET /api/clients/{id}"""

    async def test_get_client_not_found(self, admin_client):
        resp = await admin_client.get("/api/clients/99999")
        assert resp.status_code == 404

    async def test_get_client_invalid_id(self, admin_client):
        resp = await admin_client.get("/api/clients/abc")
        assert resp.status_code == 422

"""Tests for user management endpoints.

Covers:
- List users → 200
- Create user validation → 422
- Auth required → 401
- Member gets sanitized user list
- Admin required for create
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestUsersList:
    """GET /api/users"""

    async def test_list_users_returns_200(self, admin_client):
        resp = await admin_client.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_list_users_pagination(self, admin_client):
        resp = await admin_client.get(
            "/api/users", params={"page": 1, "page_size": 10}
        )
        assert resp.status_code == 200

    async def test_list_users_member_gets_200(self, member_client):
        resp = await member_client.get("/api/users")
        assert resp.status_code == 200

    async def test_list_users_invalid_page(self, admin_client):
        resp = await admin_client.get("/api/users", params={"page": 0})
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestUsersAuth:
    """Auth required for /api/users"""

    async def test_list_users_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/users")
        assert resp.status_code == 401

    async def test_create_user_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/users", json={})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestUserCreate:
    """POST /api/users"""

    async def test_create_user_missing_fields_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/users",
            json={"email": "test@test.com"},
        )
        assert resp.status_code == 422

    async def test_create_user_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/users", json={})
        assert resp.status_code == 422

    async def test_create_user_short_password_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/users",
            json={
                "email": "test@test.com",
                "password": "short",
                "full_name": "Test User",
            },
        )
        assert resp.status_code == 422

    async def test_create_user_invalid_email_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/users",
            json={
                "email": "not-an-email",
                "password": "ValidPass123",
                "full_name": "Test User",
            },
        )
        assert resp.status_code == 422

    async def test_create_user_missing_full_name_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/users",
            json={
                "email": "test@test.com",
                "password": "ValidPass123",
            },
        )
        assert resp.status_code == 422

    async def test_create_user_member_forbidden(self, member_client):
        resp = await member_client.post(
            "/api/users",
            json={
                "email": "new@test.com",
                "password": "ValidPass123",
                "full_name": "New User",
            },
        )
        assert resp.status_code == 403

"""Tests for project CRUD endpoints.

Covers:
- List projects → 200
- Create project validation → 422
- Get project → 404
- List project phases
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestProjectsList:
    """GET /api/projects"""

    async def test_list_projects_returns_200(self, admin_client):
        resp = await admin_client.get("/api/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_list_projects_with_status_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/projects",
            params={"status": "active", "page": 1, "page_size": 10},
        )
        assert resp.status_code == 200

    async def test_list_projects_by_client(self, admin_client):
        resp = await admin_client.get(
            "/api/projects", params={"client_id": 1}
        )
        assert resp.status_code == 200

    async def test_list_projects_by_type(self, admin_client):
        resp = await admin_client.get(
            "/api/projects", params={"project_type": "seo_audit"}
        )
        assert resp.status_code == 200

    async def test_list_projects_pagination(self, admin_client):
        resp = await admin_client.get(
            "/api/projects", params={"page": 2, "page_size": 5}
        )
        assert resp.status_code == 200

    async def test_list_projects_invalid_page(self, admin_client):
        resp = await admin_client.get(
            "/api/projects", params={"page": 0}
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestProjectsAuth:
    """Auth required for /api/projects"""

    async def test_list_projects_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/projects")
        assert resp.status_code == 401

    async def test_create_project_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/projects", json={"name": "Test"})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestProjectCreate:
    """POST /api/projects"""

    async def test_create_project_missing_name_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/projects",
            json={"description": "No name provided"},
        )
        assert resp.status_code == 422

    async def test_create_project_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/projects", json={})
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestProjectDetail:
    """GET /api/projects/{id}"""

    async def test_get_project_not_found(self, admin_client):
        resp = await admin_client.get("/api/projects/99999")
        assert resp.status_code == 404

    async def test_get_project_invalid_id(self, admin_client):
        resp = await admin_client.get("/api/projects/abc")
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestProjectPhases:
    """GET /api/projects/{id}/phases"""

    async def test_list_phases_returns_200_or_404(self, admin_client):
        resp = await admin_client.get("/api/projects/1/phases")
        assert resp.status_code in (200, 404)

    async def test_create_phase_missing_name_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/projects/1/phases",
            json={},
        )
        assert resp.status_code == 422

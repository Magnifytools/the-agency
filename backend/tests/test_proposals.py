"""Tests for proposal CRUD endpoints.

Covers:
- List proposals → 200
- Create proposal validation → 422
- Get proposal → 404
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestProposalsList:
    """GET /api/proposals"""

    async def test_list_proposals_returns_200(self, admin_client):
        resp = await admin_client.get("/api/proposals")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_proposals_with_status_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/proposals",
            params={"status": "draft", "limit": 10, "offset": 0},
        )
        assert resp.status_code == 200

    async def test_list_proposals_by_client(self, admin_client):
        resp = await admin_client.get(
            "/api/proposals", params={"client_id": 1}
        )
        assert resp.status_code == 200

    async def test_list_proposals_by_lead(self, admin_client):
        resp = await admin_client.get(
            "/api/proposals", params={"lead_id": 1}
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestProposalsAuth:
    """Auth required for /api/proposals"""

    async def test_list_proposals_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/proposals")
        assert resp.status_code == 401

    async def test_create_proposal_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/proposals", json={"title": "Test"})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestProposalCreate:
    """POST /api/proposals"""

    async def test_create_proposal_missing_title_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/proposals",
            json={"company_name": "Acme"},
        )
        assert resp.status_code == 422

    async def test_create_proposal_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/proposals", json={})
        assert resp.status_code == 422

    async def test_create_proposal_title_too_long_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/proposals",
            json={"title": "x" * 301},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestProposalDetail:
    """GET /api/proposals/{id}"""

    async def test_get_proposal_not_found(self, admin_client):
        resp = await admin_client.get("/api/proposals/99999")
        assert resp.status_code == 404

    async def test_get_proposal_invalid_id(self, admin_client):
        resp = await admin_client.get("/api/proposals/abc")
        assert resp.status_code == 422

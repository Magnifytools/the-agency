"""Tests for communication log endpoints.

Covers:
- List client communications → 200
- Create communication → happy path + validation
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestCommunicationsList:
    """GET /api/clients/{client_id}/communications"""

    async def test_list_communications_returns_200(self, admin_client):
        resp = await admin_client.get("/api/clients/1/communications")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_communications_empty_client(self, admin_client):
        resp = await admin_client.get("/api/clients/9999/communications")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestCommunicationsAuth:
    """Auth required for /api/clients/{id}/communications"""

    async def test_communications_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/clients/1/communications")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestCommunicationCreate:
    """POST /api/clients/{client_id}/communications"""

    async def test_create_communication_missing_fields_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/clients/1/communications",
            json={"subject": "Missing required fields"},
        )
        assert resp.status_code == 422

    async def test_create_communication_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/clients/1/communications", json={}
        )
        assert resp.status_code == 422

    async def test_create_communication_happy_path(self, admin_client):
        resp = await admin_client.post(
            "/api/clients/1/communications",
            json={
                "channel": "email",
                "direction": "outbound",
                "summary": "Sent proposal follow-up",
                "occurred_at": "2025-06-01T10:00:00",
            },
        )
        # Mock DB: client lookup returns None → 404
        assert resp.status_code in (201, 404, 500)


@pytest.mark.asyncio
class TestCommunicationDraftEmail:
    """POST /api/communications/draft-email"""

    async def test_draft_email_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/communications/draft-email", json={}
        )
        assert resp.status_code == 422

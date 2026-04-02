"""Tests for CRM leads endpoints.

Covers:
- List leads → 200
- Create lead validation → 422
- Get lead → 404
- Pipeline summary → 200
- Reminders → 200
- Auth required → 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app


@pytest.mark.asyncio
class TestLeadsList:
    """GET /api/leads"""

    async def test_list_leads_returns_200(self, admin_client):
        resp = await admin_client.get("/api/leads")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or isinstance(data, list)

    async def test_list_leads_with_status_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/leads",
            params={"status": "new", "limit": 10},
        )
        assert resp.status_code == 200

    async def test_list_leads_with_source_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/leads",
            params={"source": "referral"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestLeadsAuth:
    """Auth required for /api/leads"""

    async def test_list_leads_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/leads")
        assert resp.status_code == 401

    async def test_create_lead_no_auth_returns_401(self):
        app.dependency_overrides.clear()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/leads", json={})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestLeadCreate:
    """POST /api/leads"""

    async def test_create_lead_missing_company_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/leads",
            json={"contact_name": "John"},
        )
        assert resp.status_code == 422

    async def test_create_lead_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post("/api/leads", json={})
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestLeadDetail:
    """GET /api/leads/{id}"""

    async def test_get_lead_not_found(self, admin_client):
        resp = await admin_client.get("/api/leads/99999")
        assert resp.status_code == 404

    async def test_get_lead_invalid_id(self, admin_client):
        resp = await admin_client.get("/api/leads/abc")
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestPipelineSummary:
    """GET /api/leads/pipeline-summary"""

    async def test_pipeline_summary_returns_200(self, admin_client):
        resp = await admin_client.get("/api/leads/pipeline-summary")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestLeadReminders:
    """GET /api/leads/reminders"""

    async def test_reminders_returns_200(self, admin_client):
        resp = await admin_client.get("/api/leads/reminders")
        assert resp.status_code == 200

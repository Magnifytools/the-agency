"""Tests for proposal CRUD routes."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestProposalsList:
    async def test_list_proposals_returns_200(self, admin_client):
        resp = await admin_client.get("/api/proposals")
        assert resp.status_code == 200

    async def test_list_proposals_filter_status(self, admin_client):
        resp = await admin_client.get("/api/proposals?status=draft")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestProposalsCrud:
    async def test_get_nonexistent_proposal_404(self, admin_client):
        resp = await admin_client.get("/api/proposals/99999")
        assert resp.status_code == 404

    async def test_create_proposal_422_missing_fields(self, admin_client):
        resp = await admin_client.post("/api/proposals", json={})
        assert resp.status_code == 422

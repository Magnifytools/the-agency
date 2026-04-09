"""Tests for client contacts routes."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestContactsList:
    async def test_list_contacts_returns_200(self, admin_client):
        resp = await admin_client.get("/api/clients/1/contacts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_contacts_nonexistent_client(self, admin_client):
        resp = await admin_client.get("/api/clients/99999/contacts")
        assert resp.status_code == 200  # empty list, not 404


@pytest.mark.asyncio
class TestContactsCrud:
    async def test_create_contact_422_missing_fields(self, admin_client):
        resp = await admin_client.post("/api/clients/1/contacts", json={})
        assert resp.status_code == 422

    async def test_delete_nonexistent_contact_404(self, admin_client):
        resp = await admin_client.delete("/api/clients/1/contacts/99999")
        assert resp.status_code == 404

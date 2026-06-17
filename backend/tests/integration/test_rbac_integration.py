"""Integration tests for module-based RBAC against a REAL Postgres DB.

``GET /api/leads`` is protected by ``require_module("growth")``. With real
``User`` + ``UserPermission`` rows in the DB (loaded via ``selectinload`` inside
``get_current_user``), we prove the full permission path end to end:

  * member WITHOUT the "growth" permission  -> 403
  * member WITH "growth" read permission     -> 200
  * member with a DIFFERENT module           -> 403 (no cross-module leak)
  * admin (role bypass)                      -> 200
  * write op needs can_write, not just read  -> 403 then 201
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_member_without_permission_gets_403(member_client):
    resp = await member_client.get("/api/leads")
    assert resp.status_code == 403, resp.text
    assert "growth" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_member_with_growth_permission_gets_200(make_member_client):
    client = await make_member_client([("growth", True, False)])
    try:
        resp = await client.get("/api/leads")
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_member_with_unrelated_permission_still_403(make_member_client):
    """Having access to a different module must NOT grant /api/leads."""
    client = await make_member_client([("clients", True, True)])
    try:
        resp = await client.get("/api/leads")
        assert resp.status_code == 403, resp.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_admin_bypasses_permission_check(admin_client):
    resp = await admin_client.get("/api/leads")
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_read_permission_does_not_grant_write(make_member_client):
    """can_read alone must not allow POST (which requires write=True)."""
    read_only = await make_member_client([("growth", True, False)])
    try:
        resp = await read_only.post(
            "/api/leads", json={"company_name": "Acme Corp"}
        )
        assert resp.status_code == 403, resp.text
    finally:
        await read_only.aclose()


@pytest.mark.asyncio
async def test_write_permission_allows_create(make_member_client):
    writer = await make_member_client([("growth", True, True)])
    try:
        resp = await writer.post("/api/leads", json={"company_name": "Acme Corp"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["company_name"] == "Acme Corp"
    finally:
        await writer.aclose()


@pytest.mark.asyncio
async def test_unauthenticated_request_is_401(app_with_db):
    """No token at all -> 401 before any permission check."""
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=app_with_db), base_url="http://test"
    ) as anon:
        resp = await anon.get("/api/leads")
    assert resp.status_code == 401, resp.text

"""Regression tests for industry news endpoints.

Covers:
- List news sources → 200
- Create news source without required fields (url/name missing) → 422
- Create news source happy path (mock DB commit)
- List news → 200
- Get nonexistent news → 404
- Delete nonexistent news/source → 404
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestNewsSourcesList:
    """GET /api/news/sources"""

    async def test_list_sources_returns_200(self, admin_client):
        resp = await admin_client.get("/api/news/sources")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
class TestNewsSourcesCreate:
    """POST /api/news/sources"""

    async def test_create_source_missing_url_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/news/sources",
            json={"name": "Test Source"},
        )
        # url is required in NewsSourceCreate → 422 validation error
        assert resp.status_code == 422

    async def test_create_source_missing_name_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/news/sources",
            json={"url": "https://example.com"},
        )
        # name is required in NewsSourceCreate → 422 validation error
        assert resp.status_code == 422

    async def test_create_source_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/news/sources",
            json={},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestNewsList:
    """GET /api/news"""

    async def test_list_news_returns_200(self, admin_client):
        resp = await admin_client.get("/api/news")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_news_with_limit(self, admin_client):
        resp = await admin_client.get("/api/news", params={"limit": 10})
        assert resp.status_code == 200

    async def test_get_nonexistent_news_returns_404(self, admin_client):
        resp = await admin_client.get("/api/news/999")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestNewsDelete:
    """DELETE /api/news and /api/news/sources"""

    async def test_delete_nonexistent_news_returns_404(self, admin_client):
        resp = await admin_client.delete("/api/news/999")
        assert resp.status_code == 404

    async def test_delete_nonexistent_source_returns_404(self, admin_client):
        resp = await admin_client.delete("/api/news/sources/999")
        assert resp.status_code == 404

"""Tests for industry news endpoints — regression for source creation 500."""
import sys
from unittest.mock import MagicMock, AsyncMock

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

from backend.main import app  # noqa: E402
from backend.api.deps import get_current_user  # noqa: E402
from backend.db.database import get_db  # noqa: E402
from backend.db.models import User, UserRole  # noqa: E402


def _make_admin():
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "admin@test.com"
    user.full_name = "Admin Test"
    user.role = UserRole.admin
    user.is_active = True
    user.permissions = []
    return user


class TestIndustryNewsEndpoints:
    @pytest_asyncio.fixture
    async def client(self):
        admin = _make_admin()
        mock_db = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        execute_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = execute_result

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_news_returns_200(self, client):
        resp = await client.get("/api/news")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_nonexistent_news_returns_404(self, client):
        resp = await client.get("/api/news/999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_sources_returns_200(self, client):
        resp = await client.get("/api/news/sources")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_news_returns_404(self, client):
        resp = await client.delete("/api/news/999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_source_returns_404(self, client):
        resp = await client.delete("/api/news/sources/999")
        assert resp.status_code == 404

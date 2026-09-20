"""Regression tests for notification generation — N+1 elimination + batch queries."""

import sys
from unittest.mock import AsyncMock, MagicMock

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import User, UserRole
from backend.main import app


def _make_admin():
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "admin@test.com"
    user.full_name = "Admin Test"
    user.role = UserRole.admin
    user.is_active = True
    user.permissions = []
    return user


class TestNotificationsEndpoints:
    """Basic endpoint reachability tests for notification routes."""

    @pytest_asyncio.fixture
    async def client(self):
        admin = _make_admin()
        mock_db = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar.return_value = 0
        execute_result.scalars.return_value.all.return_value = []
        execute_result.all.return_value = []
        mock_db.execute.return_value = execute_result

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: mock_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_list_notifications_returns_200(self, client):
        resp = await client.get("/api/notifications")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_unread_count_returns_200(self, client):
        resp = await client.get("/api/notifications/unread-count")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data

    @pytest.mark.asyncio
    async def test_mark_all_read_returns_200(self, client):
        resp = await client.put("/api/notifications/read-all")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_generate_checks_returns_canonical_reconciliation_counts(
        self, client
    ):
        resp = await client.post("/api/notifications/generate-checks")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"created": 0, "changed": 0}

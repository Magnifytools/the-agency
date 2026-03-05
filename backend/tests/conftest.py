import sys
from unittest.mock import MagicMock, AsyncMock

# ── Mock asyncpg before anything imports database.py ────────────────
# The system Python may not have asyncpg installed (it runs inside Docker).
# We mock the engine so tests can import the FastAPI app without a real DB.
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

from backend.main import app  # noqa: E402
from backend.api.deps import get_current_user  # noqa: E402
from backend.db.database import get_db  # noqa: E402
from backend.db.models import User, UserRole, UserPermission  # noqa: E402


def _make_admin():
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "admin@test.com"
    user.full_name = "Admin Test"
    user.role = UserRole.admin
    user.is_active = True
    user.hourly_rate = 40.0
    user.weekly_hours = 40.0
    user.preferences = None
    user.permissions = []
    return user


def _make_member():
    user = MagicMock(spec=User)
    user.id = 2
    user.email = "member@test.com"
    user.full_name = "Member Test"
    user.role = UserRole.member
    user.is_active = True
    user.hourly_rate = 30.0
    user.weekly_hours = 40.0
    user.preferences = None
    perm = MagicMock(spec=UserPermission)
    perm.module = "clients"
    perm.can_read = True
    perm.can_write = False
    user.permissions = [perm]
    return user


@pytest.fixture
def admin_user():
    return _make_admin()


@pytest.fixture
def member_user():
    return _make_member()


def _make_mock_db():
    """AsyncMock DB where execute() returns a MagicMock (not AsyncMock).

    AsyncMock child attributes are also AsyncMock — calling them returns
    un-awaited coroutines, causing serialization errors in routes that do
    `result.scalar()` or `result.scalars().all()`. Using MagicMock for the
    execute return value avoids that.
    """
    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar.return_value = 0
    execute_result.scalars.return_value.all.return_value = []
    execute_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = execute_result
    return mock_db


@pytest_asyncio.fixture
async def admin_client(admin_user):
    mock_db = _make_mock_db()

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def member_client(member_user):
    mock_db = _make_mock_db()

    app.dependency_overrides[get_current_user] = lambda: member_user
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()

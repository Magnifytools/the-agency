import sys
from unittest.mock import MagicMock, AsyncMock

# ── Mock asyncpg before anything imports database.py ────────────────
# The system Python may not have asyncpg installed (it runs inside Docker).
# We mock the engine so tests can import the FastAPI app without a real DB.
if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

import pytest  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402

from backend.main import app  # noqa: E402
from backend.api.deps import get_current_user  # noqa: E402
from backend.db.database import get_db  # noqa: E402
from backend.db.models import User, UserRole, UserPermission  # noqa: E402


@pytest.fixture
def admin_user():
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "admin@test.com"
    user.full_name = "Admin Test"
    user.role = UserRole.admin
    user.is_active = True
    user.hourly_rate = 40.0
    user.weekly_hours = 40.0
    user.permissions = []
    return user


@pytest.fixture
def member_user():
    user = MagicMock(spec=User)
    user.id = 2
    user.email = "member@test.com"
    user.full_name = "Member Test"
    user.role = UserRole.member
    user.is_active = True
    user.hourly_rate = 30.0
    user.weekly_hours = 40.0
    # Add a permission for clients module
    perm = MagicMock(spec=UserPermission)
    perm.module = "clients"
    perm.can_read = True
    perm.can_write = False
    user.permissions = [perm]
    return user


@pytest.fixture
async def admin_client(admin_user):
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def member_client(member_user):
    mock_db = AsyncMock()

    app.dependency_overrides[get_current_user] = lambda: member_user
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()

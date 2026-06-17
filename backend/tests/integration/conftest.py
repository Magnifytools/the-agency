"""Real-PostgreSQL integration test harness for The Agency backend.

Unlike the mocked unit-test suite in ``backend/tests/conftest.py`` (which stubs
out ``asyncpg`` and overrides ``get_db`` with an ``AsyncMock`` so no real SQL is
ever executed), this harness runs against a **real** PostgreSQL database. That
means the tests here exercise actual DDL, constraints, indexes and transactional
behaviour — the bugs the mocked suite can't catch.

Database selection (in order):
    1. ``TEST_DATABASE_URL`` env var (asyncpg URL), e.g.
       ``postgresql+asyncpg://agency:agency@localhost:5432/the_agency_test``
    2. The local docker-compose / Homebrew Postgres default:
       ``postgresql+asyncpg://agency:agency@localhost:5432/the_agency_test``

If no database is reachable, *every* test in this package is SKIPPED with a
clear reason (so CI without a DB stays green). To run them:

    docker compose up -d            # or have a local Postgres on :5432
    # ensure a ``the_agency_test`` database exists (auto-created if perms allow)
    cd backend && source venv/bin/activate
    python -m pytest tests/integration -v -m integration

Isolation model: the schema is created ONCE per session via
``Base.metadata.create_all`` + the app's ``_ensure_indexes_v11`` migration (so
the partial unique index ``uq_time_entries_active_timer`` exists). Each test
runs inside a SAVEPOINT-backed transaction that is rolled back at teardown, so
tests never see each other's writes and the DB is left clean.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys

import pytest
import pytest_asyncio

# ── Force the REAL asyncpg ──────────────────────────────────────────
# The parent conftest (backend/tests/conftest.py) does
# ``sys.modules["asyncpg"] = MagicMock()`` when asyncpg isn't already imported.
# For integration tests we need the genuine driver, so restore it here. asyncpg
# is a hard dependency of the backend's requirements, so this import must work
# for the harness to run at all.
from unittest.mock import MagicMock as _MagicMock  # noqa: E402

# The parent conftest only stubs asyncpg with a MagicMock when the real driver
# is NOT importable (``if "asyncpg" not in sys.modules``); it imports the stub
# lazily. When the genuine asyncpg is installed (as it is in the backend venv)
# we make sure ``sys.modules["asyncpg"]`` points at the real module so the
# SQLAlchemy asyncpg dialect drives a real connection rather than a MagicMock.
_stub = sys.modules.get("asyncpg")
if isinstance(_stub, _MagicMock):
    del sys.modules["asyncpg"]

try:
    import asyncpg  # noqa: F401  (real driver)
    _REAL_ASYNCPG = not isinstance(asyncpg, _MagicMock)
except Exception:  # pragma: no cover - asyncpg should be installed
    _REAL_ASYNCPG = False

from httpx import AsyncClient, ASGITransport  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings  # noqa: E402
from backend.core.security import create_access_token  # noqa: E402


DEFAULT_TEST_DB_URL = (
    "postgresql+asyncpg://agency:agency@localhost:5432/the_agency_test"
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)


def _db_reachable(url: str) -> tuple[bool, str]:
    """Best-effort connectivity probe. Returns (ok, reason)."""
    if not _REAL_ASYNCPG:
        return False, "real asyncpg driver is not importable"

    async def _check() -> None:
        # Translate the SQLAlchemy URL to raw asyncpg params.
        raw = url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn=raw, timeout=5)
        await conn.execute("SELECT 1")
        await conn.close()

    try:
        asyncio.new_event_loop().run_until_complete(_check())
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"cannot reach test DB at {url!r}: {type(exc).__name__}: {exc}"


_DB_OK, _DB_REASON = _db_reachable(TEST_DATABASE_URL)

# Skip the ENTIRE integration package cleanly if the DB isn't reachable, and
# mark everything here as ``integration`` so ``-m integration`` selects them.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DB_OK, reason=_DB_REASON or "no test database"),
]


# Module-global cache: build the schema exactly once per process even though
# the engine fixture is function-scoped (a session-scoped async fixture clashes
# with pytest-asyncio's function-scoped event loop under asyncio_mode=auto).
_SCHEMA_READY = False


async def _ensure_schema(eng) -> None:
    """Create the full schema + the v11 index migration once per process."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    from backend.db.models import Base

    async with eng.begin() as conn:
        # Start from a clean slate so a stale schema from a previous run can't
        # mask model changes, then recreate everything.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Apply the real startup index migration against THIS engine. The migration
    # module reads ``backend.db.database.engine`` internally, so temporarily
    # point that at our test engine while it runs.
    import backend.db.database as db_module
    from backend.startup import migrations as mig

    original_engine = db_module.engine
    db_module.engine = eng
    try:
        await mig._ensure_indexes_v11()
    finally:
        db_module.engine = original_engine

    _SCHEMA_READY = True


@pytest_asyncio.fixture
async def engine():
    """A real async engine bound to the test database.

    Function-scoped (to satisfy pytest-asyncio's per-test event loop) but the
    schema/migration work runs only once thanks to ``_ensure_schema``. The
    schema includes the partial unique index ``uq_time_entries_active_timer``
    (the whole point of the timer concurrency test).
    """
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    await _ensure_schema(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncSession:
    """Transaction-per-test session, rolled back at teardown.

    Uses the SQLAlchemy "join an external transaction" pattern: an outer
    transaction + a SAVEPOINT that is restarted whenever the inner code commits,
    so route handlers that call ``db.commit()`` don't actually persist anything
    beyond the test.
    """
    # SQLAlchemy 2.0 "join an external transaction" via join_transaction_mode:
    # the session opens SAVEPOINTs for its commits inside our outer transaction,
    # which we roll back at teardown — so route handlers' db.commit() calls don't
    # persist beyond the test. No manual after_transaction_end event hack needed.
    connection = await engine.connect()
    trans = await connection.begin()

    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def app_with_db(db_session):
    """The FastAPI app wired to the real transactional ``db_session``.

    Overrides ``get_db`` to yield the same per-test session, so requests and the
    test body share one rolled-back transaction. Returns the app; auth is layered
    on by the client fixtures below (real JWT, NOT a get_current_user override).
    """
    from backend.main import app
    from backend.db.database import get_db

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── User / auth factories ───────────────────────────────────────────

def _auth_headers(user_id: int) -> dict[str, str]:
    """Real Bearer header. ``get_current_user`` accepts a Bearer credential and
    loads the user from the DB, so the user row must exist in ``db_session``."""
    token = create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


async def _create_user(db_session, *, email, full_name, role, permissions=None):
    """Insert a real User (+ optional UserPermission rows) into the test DB."""
    from backend.core.security import hash_password
    from backend.db.models import User, UserPermission, UserRole

    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password("test-password"),
        role=role,
        is_active=True,
        hourly_rate=40.0,
        weekly_hours=40.0,
    )
    db_session.add(user)
    await db_session.flush()  # assign user.id without ending the outer tx

    for module, can_read, can_write in (permissions or []):
        db_session.add(
            UserPermission(
                user_id=user.id,
                module=module,
                can_read=can_read,
                can_write=can_write,
            )
        )
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session):
    from backend.db.models import UserRole

    return await _create_user(
        db_session,
        email="admin-int@test.com",
        full_name="Admin Integration",
        role=UserRole.admin,
    )


@pytest_asyncio.fixture
async def member_user(db_session):
    """A plain member with NO module permissions (RBAC negative case)."""
    from backend.db.models import UserRole

    return await _create_user(
        db_session,
        email="member-int@test.com",
        full_name="Member Integration",
        role=UserRole.member,
        permissions=[],
    )


@pytest_asyncio.fixture
async def admin_client(app_with_db, admin_user):
    headers = _auth_headers(admin_user.id)
    async with AsyncClient(
        transport=ASGITransport(app=app_with_db),
        base_url="http://test",
        headers=headers,
    ) as client:
        client.test_user = admin_user  # type: ignore[attr-defined]
        yield client


@pytest_asyncio.fixture
async def member_client(app_with_db, member_user):
    headers = _auth_headers(member_user.id)
    async with AsyncClient(
        transport=ASGITransport(app=app_with_db),
        base_url="http://test",
        headers=headers,
    ) as client:
        client.test_user = member_user  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def make_member_client(app_with_db, db_session):
    """Factory: build a member client with a specific set of permissions.

    Usage:
        client = await make_member_client([("growth", True, False)])
    """
    from backend.db.models import UserRole

    created: list[int] = []

    async def _factory(permissions):
        user = await _create_user(
            db_session,
            email=f"member-{len(created)}-int@test.com",
            full_name=f"Member {len(created)}",
            role=UserRole.member,
            permissions=permissions,
        )
        created.append(user.id)
        headers = _auth_headers(user.id)
        client = AsyncClient(
            transport=ASGITransport(app=app_with_db),
            base_url="http://test",
            headers=headers,
        )
        client.test_user = user  # type: ignore[attr-defined]
        return client

    return _factory

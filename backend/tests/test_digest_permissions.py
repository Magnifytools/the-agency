"""Digest permission tests.

Verify that non-admin users with the correct module permissions can
access digest endpoints, and that ownership / status rules are enforced.
"""
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock

from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import (
    User, UserRole, UserPermission, WeeklyDigest, DigestStatus, DigestTone,
)


def _make_digest_member():
    """Create a non-admin user with digests read+write permissions."""
    user = MagicMock(spec=User)
    user.id = 10
    user.email = "digestwriter@test.com"
    user.full_name = "Digest Writer"
    user.role = UserRole.member
    user.is_active = True
    user.hourly_rate = 30.0
    user.weekly_hours = 40.0
    user.preferences = None
    user.region = None
    user.locality = None
    user.short_name = None
    user.birthday = None
    user.job_title = None
    user.morning_reminder_time = "09:00"
    user.evening_reminder_time = "18:00"
    user.onboarding_completed = False

    read_perm = MagicMock(spec=UserPermission)
    read_perm.module = "digests"
    read_perm.can_read = True
    read_perm.can_write = True

    user.permissions = [read_perm]
    return user


def _make_mock_db():
    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar.return_value = 0
    execute_result.scalar_one_or_none.return_value = None
    execute_result.scalars.return_value.all.return_value = []
    execute_result.scalars.return_value.first.return_value = None
    mock_db.execute.return_value = execute_result
    return mock_db


@pytest_asyncio.fixture
async def digest_member():
    return _make_digest_member()


@pytest_asyncio.fixture
async def digest_member_client(digest_member):
    mock_db = _make_mock_db()

    app.dependency_overrides[get_current_user] = lambda: digest_member
    app.dependency_overrides[get_db] = lambda: mock_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, mock_db, digest_member

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test 1: Non-admin with digests read permission can list digests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_member_with_digest_permission_can_list(digest_member_client):
    client, mock_db, _ = digest_member_client
    response = await client.get("/api/digests")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Test 2: Non-admin with digests write permission can generate a digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_member_with_digest_write_can_generate(digest_member_client):
    """POST /api/digests/generate should be accessible to members with write permission."""
    from unittest.mock import patch
    from datetime import date

    client, mock_db, member = digest_member_client

    # Mock: client lookup returns a valid client
    fake_client = MagicMock()
    fake_client.id = 1
    fake_client.name = "Test Client"

    # Mock: no previous drafts
    drafts_result = MagicMock()
    drafts_result.scalars.return_value.all.return_value = []

    client_result = MagicMock()
    client_result.scalar_one_or_none.return_value = fake_client

    # DB execute returns different things on successive calls
    mock_db.execute.side_effect = [client_result, drafts_result]

    fake_digest = MagicMock(spec=WeeklyDigest)
    fake_digest.id = 1
    fake_digest.client_id = 1
    fake_digest.client = fake_client
    fake_digest.period_start = date(2026, 3, 9)
    fake_digest.period_end = date(2026, 3, 15)
    fake_digest.status = DigestStatus.draft
    fake_digest.tone = DigestTone.cercano
    fake_digest.content = {"greeting": "Hola", "date": "2026-03-15", "sections": {}, "closing": "Saludos"}
    fake_digest.raw_context = {}
    fake_digest.generated_at = None
    fake_digest.edited_at = None
    fake_digest.created_by = member.id
    fake_digest.creator = member
    fake_digest.created_at = "2026-01-01T00:00:00"
    fake_digest.updated_at = "2026-01-01T00:00:00"

    with (
        patch(
            "backend.api.routes.digests.collect_digest_data",
            new_callable=AsyncMock,
            return_value={"tasks": [], "time_entries": []},
        ),
        patch(
            "backend.api.routes.digests.generate_digest_content",
            new_callable=AsyncMock,
            return_value={"greeting": "Hola", "date": "2026-03-15", "sections": {}, "closing": "Saludos"},
        ),
        patch(
            "backend.api.routes.digests.safe_refresh",
            new_callable=AsyncMock,
        ),
        patch(
            "backend.api.routes.digests._to_response",
            return_value={
                "id": 1, "client_id": 1, "client_name": "Test Client",
                "period_start": "2026-03-09", "period_end": "2026-03-15",
                "status": "draft", "tone": "cercano", "content": None,
                "raw_context": None, "generated_at": None, "edited_at": None,
                "created_by": member.id, "creator_name": member.full_name,
                "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
            },
        ),
    ):
        response = await client.post(
            "/api/digests/generate",
            json={
                "client_id": 1,
                "period_start": "2026-03-09",
                "period_end": "2026-03-15",
            },
        )

    # Should not be 403 — member has write permission
    assert response.status_code != 403, "Member with digest write permission should not be blocked"


# ---------------------------------------------------------------------------
# Test 3: Non-admin can delete their own draft digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_member_can_delete_own_draft(digest_member_client):
    client, mock_db, member = digest_member_client

    fake_digest = MagicMock(spec=WeeklyDigest)
    fake_digest.id = 5
    fake_digest.created_by = member.id  # same user
    fake_digest.status = DigestStatus.draft

    result = MagicMock()
    result.scalar_one_or_none.return_value = fake_digest
    mock_db.execute.return_value = result

    response = await client.delete("/api/digests/5")
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Test 4: Non-admin can delete their own reviewed digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_member_can_delete_own_reviewed(digest_member_client):
    client, mock_db, member = digest_member_client

    fake_digest = MagicMock(spec=WeeklyDigest)
    fake_digest.id = 6
    fake_digest.created_by = member.id
    fake_digest.status = DigestStatus.reviewed

    result = MagicMock()
    result.scalar_one_or_none.return_value = fake_digest
    mock_db.execute.return_value = result

    response = await client.delete("/api/digests/6")
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Test 5: Non-admin cannot delete a sent digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_member_cannot_delete_sent_digest(digest_member_client):
    client, mock_db, member = digest_member_client

    fake_digest = MagicMock(spec=WeeklyDigest)
    fake_digest.id = 7
    fake_digest.created_by = member.id
    fake_digest.status = DigestStatus.sent

    result = MagicMock()
    result.scalar_one_or_none.return_value = fake_digest
    mock_db.execute.return_value = result

    response = await client.delete("/api/digests/7")
    assert response.status_code == 409, f"Expected 409 but got {response.status_code}: {response.text}"

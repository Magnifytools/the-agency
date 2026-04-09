"""Phantom 500 regression tests.

Verify that side-effect failures (notifications, sync, reload) do NOT
cause the primary operation to return a 500.  The core mutation must
succeed and return its normal status code even when ancillary work fails.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from backend.db.models import (
    Task, TaskStatus, TaskPriority, TimeEntry, ProjectEvidence, EvidenceType, NewsSource,
)


# ---------------------------------------------------------------------------
# Test 1: Creating a task with notification failure still returns 201
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_returns_201_when_notification_fails(admin_client, admin_user):
    """POST /api/tasks should return 201 even if the notification service raises."""
    fake_task = MagicMock(spec=Task)
    fake_task.id = 99
    fake_task.title = "Test task"
    fake_task.description = None
    fake_task.status = TaskStatus.pending
    fake_task.priority = TaskPriority.medium
    fake_task.estimated_minutes = None
    fake_task.actual_minutes = None
    fake_task.due_date = None
    fake_task.client_id = None
    fake_task.category_id = None
    fake_task.assigned_to = 5  # triggers notification path
    fake_task.project_id = None
    fake_task.phase_id = None
    fake_task.depends_on = None
    fake_task.created_by = admin_user.id
    fake_task.scheduled_date = None
    fake_task.waiting_for = None
    fake_task.follow_up_date = None
    fake_task.created_at = "2026-01-01T00:00:00"
    fake_task.updated_at = "2026-01-01T00:00:00"
    fake_task.is_recurring = False
    fake_task.recurrence_pattern = None
    fake_task.recurrence_day = None
    fake_task.recurrence_end_date = None
    fake_task.recurring_parent_id = None
    fake_task.client = None
    fake_task.category = None
    fake_task.assigned_user = None
    fake_task.creator = None
    fake_task.project = None
    fake_task.phase = None
    fake_task.dependency = None
    fake_task.recurring_parent = None
    fake_task.checklist_items = []

    with (
        patch(
            "backend.api.routes.tasks._load_task_for_response",
            new_callable=AsyncMock,
            return_value=fake_task,
        ),
        patch(
            "backend.services.notification_service.create_notification",
            new_callable=AsyncMock,
            side_effect=Exception("notification service down"),
        ),
    ):
        response = await admin_client.post(
            "/api/tasks",
            json={"title": "Test task", "assigned_to": 5},
        )

    assert response.status_code == 201, f"Expected 201 but got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 2: Stopping a timer with sync failure still returns 200
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_timer_returns_200_when_sync_fails(admin_client, admin_user):
    """POST /api/timer/stop should return 200 even if _sync_task_actual_minutes raises."""
    from datetime import datetime, timezone

    fake_entry = MagicMock(spec=TimeEntry)
    fake_entry.id = 42
    fake_entry.task_id = 10
    fake_entry.user_id = admin_user.id
    fake_entry.minutes = None  # active timer
    fake_entry.started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    fake_entry.date = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    fake_entry.notes = None
    fake_entry.paused_at = None
    fake_entry.accumulated_seconds = 0
    fake_entry.created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    fake_entry.updated_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    fake_entry.task = None

    # For the response after stop
    stopped_entry = MagicMock(spec=TimeEntry)
    stopped_entry.id = 42
    stopped_entry.task_id = 10
    stopped_entry.user_id = admin_user.id
    stopped_entry.minutes = 30
    stopped_entry.started_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    stopped_entry.date = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    stopped_entry.notes = None
    stopped_entry.created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    stopped_entry.updated_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    stopped_entry.task = None

    # Mock the DB to return our fake active timer
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = fake_entry

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_execute_result
    mock_db.add = MagicMock()

    from backend.db.database import get_db
    from backend.api.deps import get_current_user
    from backend.main import app

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: admin_user

    with (
        patch(
            "backend.api.routes.time_entries._sync_task_actual_minutes",
            new_callable=AsyncMock,
            side_effect=Exception("sync failed"),
        ),
        patch(
            "backend.api.routes.time_entries._load_time_entry_for_response",
            new_callable=AsyncMock,
            return_value=stopped_entry,
        ),
    ):
        response = await admin_client.post("/api/timer/stop", json={})

    assert response.status_code == 200, f"Expected 200 but got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 3: Creating evidence with reload failure still returns 201
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_evidence_returns_201_when_reload_fails(admin_client, admin_user):
    """POST /api/projects/{id}/evidence should return 201 even if reload fails."""
    from datetime import datetime

    fake_evidence = MagicMock(spec=ProjectEvidence)
    fake_evidence.id = 7
    fake_evidence.project_id = 1
    fake_evidence.phase_id = None
    fake_evidence.title = "Test evidence"
    fake_evidence.url = "https://example.com"
    fake_evidence.evidence_type = "other"
    fake_evidence.description = None
    fake_evidence.created_by = admin_user.id
    fake_evidence.created_at = datetime(2026, 1, 1)
    fake_evidence.updated_at = datetime(2026, 1, 1)
    fake_evidence.file_name = None
    fake_evidence.file_mime_type = None
    fake_evidence.file_size_bytes = None
    fake_evidence.file_content = None
    fake_evidence.creator = admin_user
    fake_evidence.phase = None

    mock_db = AsyncMock()
    # _ensure_project_exists (returns a project)
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = MagicMock()  # project exists
    mock_db.execute.return_value = project_result
    # db.add must be a plain sync method (not AsyncMock)
    mock_db.add = MagicMock()

    from backend.db.database import get_db
    from backend.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    with patch(
        "backend.api.routes.evidence._reload_evidence",
        new_callable=AsyncMock,
        side_effect=Exception("reload failed"),
    ), patch(
        "backend.api.routes.evidence._to_response",
        return_value={
            "id": 7, "project_id": 1, "phase_id": None,
            "title": "Test evidence", "url": "https://example.com",
            "evidence_type": "other", "description": None,
            "created_by": admin_user.id, "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00", "file_name": None,
            "file_mime_type": None, "file_size_bytes": None,
            "creator_name": "Admin Test", "phase_name": None,
            "has_file": False, "download_url": None, "preview_url": None,
        },
    ):
        response = await admin_client.post(
            "/api/projects/1/evidence",
            json={"title": "Test evidence", "url": "https://example.com"},
        )

    assert response.status_code == 201, f"Expected 201 but got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 4: Creating a news source with reload failure still returns 201
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_news_source_returns_201_when_reload_fails(admin_user):
    """POST /api/news/sources should return 200/201 even if reload fails."""
    from datetime import datetime
    from backend.db.database import get_db
    from backend.api.deps import get_current_user
    from backend.main import app

    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar.return_value = 0
    execute_result.scalar_one_or_none.return_value = None
    execute_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = execute_result

    # Make db.add set the id/created_at on the source object so response validation passes
    def fake_add(obj):
        obj.id = 3
        obj.created_at = "2026-01-01T00:00:00"
    mock_db.add = MagicMock(side_effect=fake_add)

    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch(
                "backend.api.utils.db_helpers.reload_for_response",
                new_callable=AsyncMock,
                side_effect=Exception("reload failed"),
            ):
                response = await client.post(
                    "/api/news/sources",
                    json={"name": "Test Source", "url": "https://source.example.com", "category": "tech"},
                )

        # Should succeed (200 or 201) — not 500
        assert response.status_code in (200, 201), (
            f"Expected 200/201 but got {response.status_code}: {response.text}"
        )
    finally:
        app.dependency_overrides.clear()

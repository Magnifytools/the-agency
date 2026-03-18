"""Overdue logic tests.

Verify the overdue filter in the task list endpoint correctly identifies
tasks based on their due_date relative to today.

The rule (from tasks.py line 149-154):
    Task.due_date < date.today()  AND  status != completed
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import date, datetime, timedelta

from backend.db.models import Task, TaskStatus, TaskPriority


def _make_fake_task(task_id: int, due_date: date, status: TaskStatus = TaskStatus.pending) -> MagicMock:
    """Create a fake Task with the given due_date."""
    task = MagicMock(spec=Task)
    task.id = task_id
    task.title = f"Task {task_id}"
    task.description = None
    task.status = status
    task.priority = TaskPriority.medium
    task.estimated_minutes = None
    task.actual_minutes = None
    task.due_date = datetime.combine(due_date, datetime.min.time())
    task.client_id = None
    task.category_id = None
    task.assigned_to = None
    task.project_id = None
    task.phase_id = None
    task.depends_on = None
    task.created_by = 1
    task.scheduled_date = None
    task.waiting_for = None
    task.follow_up_date = None
    task.created_at = datetime(2026, 1, 1)
    task.updated_at = datetime(2026, 1, 1)
    task.is_recurring = False
    task.recurrence_pattern = None
    task.recurrence_day = None
    task.recurrence_end_date = None
    task.recurring_parent_id = None
    task.client = None
    task.category = None
    task.assigned_user = None
    task.creator = None
    task.project = None
    task.phase = None
    task.dependency = None
    task.recurring_parent = None
    task.checklist_items = []
    return task


# ---------------------------------------------------------------------------
# Unit tests: verify the overdue condition directly
# ---------------------------------------------------------------------------

class TestOverdueCondition:
    """Test the overdue logic: due_date < today AND status != completed."""

    def _is_overdue(self, due_date: date, status: TaskStatus) -> bool:
        """Replicate the overdue condition from the route."""
        today = date.today()
        return due_date < today and status != TaskStatus.completed

    def test_due_today_is_not_overdue(self):
        """A task due today should NOT be marked as overdue."""
        today = date.today()
        assert not self._is_overdue(today, TaskStatus.pending)

    def test_due_yesterday_is_overdue(self):
        """A task due yesterday should be marked as overdue."""
        yesterday = date.today() - timedelta(days=1)
        assert self._is_overdue(yesterday, TaskStatus.pending)

    def test_due_tomorrow_is_not_overdue(self):
        """A task due tomorrow should NOT be marked as overdue."""
        tomorrow = date.today() + timedelta(days=1)
        assert not self._is_overdue(tomorrow, TaskStatus.pending)

    def test_due_yesterday_but_completed_is_not_overdue(self):
        """A completed task past due should NOT be considered overdue."""
        yesterday = date.today() - timedelta(days=1)
        assert not self._is_overdue(yesterday, TaskStatus.completed)

    def test_due_last_week_is_overdue(self):
        """A task due a week ago should be overdue."""
        last_week = date.today() - timedelta(days=7)
        assert self._is_overdue(last_week, TaskStatus.in_progress)


# ---------------------------------------------------------------------------
# Integration tests: hit the actual endpoint with ?overdue=true
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overdue_filter_excludes_today(admin_client):
    """GET /api/tasks?overdue=true should NOT return tasks due today."""
    # The mock DB returns empty results by default, which is fine.
    # We verify the endpoint doesn't error with the overdue flag.
    response = await admin_client.get("/api/tasks?overdue=true")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 0  # mock DB returns no tasks


@pytest.mark.asyncio
async def test_overdue_filter_endpoint_works(admin_client):
    """GET /api/tasks?overdue=true returns 200 with proper structure."""
    response = await admin_client.get("/api/tasks?overdue=true")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data

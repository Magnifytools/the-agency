"""Regression tests for task CRUD endpoints.

Covers:
- List tasks → 200
- Create task without required fields (title missing) → 422
- Create task happy path (mock DB, task not found after create → 404)
- _task_to_response handles null relationships gracefully
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock


@pytest.mark.asyncio
class TestTasksList:
    """GET /api/tasks"""

    async def test_list_tasks_returns_200(self, admin_client):
        resp = await admin_client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_list_tasks_with_filters(self, admin_client):
        resp = await admin_client.get(
            "/api/tasks",
            params={"status": "pending", "page": 1, "page_size": 10},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestTaskCreate:
    """POST /api/tasks"""

    async def test_create_task_missing_title_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/tasks",
            json={"description": "No title provided"},
        )
        # title is required → 422 validation error
        assert resp.status_code == 422

    async def test_create_task_empty_body_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/tasks",
            json={},
        )
        assert resp.status_code == 422

    async def test_create_task_happy_path_mock_db(self, admin_client):
        resp = await admin_client.post(
            "/api/tasks",
            json={"title": "Test task"},
        )
        # Mock DB: _load_task_for_response returns None → 404
        # This confirms the route logic reaches the DB lookup after commit
        assert resp.status_code == 404


class TestTaskToResponse:
    """Test _task_to_response handles null relationships without crashing."""

    def test_null_client_and_project(self):
        from backend.api.routes.tasks import _task_to_response

        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.title = "Test task"
        mock_task.description = None
        mock_task.status = "pending"
        mock_task.priority = "medium"
        mock_task.estimated_minutes = None
        mock_task.actual_minutes = None
        mock_task.due_date = None
        mock_task.client_id = None
        mock_task.category_id = None
        mock_task.assigned_to = None
        mock_task.project_id = None
        mock_task.phase_id = None
        mock_task.depends_on = None
        mock_task.created_by = None
        mock_task.scheduled_date = None
        mock_task.waiting_for = None
        mock_task.follow_up_date = None
        mock_task.created_at = datetime.now(timezone.utc)
        mock_task.updated_at = datetime.now(timezone.utc)
        mock_task.is_recurring = False
        mock_task.recurrence_pattern = None
        mock_task.recurrence_day = None
        mock_task.recurrence_end_date = None
        mock_task.recurring_parent_id = None
        mock_task.link_url = None
        mock_task.checklist_items = []
        # Simulate missing relationships
        mock_task.client = None
        mock_task.category = None
        mock_task.assigned_user = None
        mock_task.project = None
        mock_task.phase = None
        mock_task.dependency = None
        mock_task.creator = None
        mock_task.recurring_parent = None

        result = _task_to_response(mock_task)
        assert result.client_name is None
        assert result.project_name is None
        assert result.assigned_user_name is None
        assert result.phase_name is None
        assert result.dependency_title is None
        assert result.created_by_name is None
        assert result.recurring_parent_title is None
        assert result.checklist_count == 0

    def test_with_relationships(self):
        from backend.api.routes.tasks import _task_to_response

        mock_task = MagicMock()
        mock_task.id = 2
        mock_task.title = "Task with relations"
        mock_task.description = "Has all relations"
        mock_task.status = "in_progress"
        mock_task.priority = "high"
        mock_task.estimated_minutes = 60
        mock_task.actual_minutes = 30
        mock_task.due_date = None
        mock_task.client_id = 1
        mock_task.category_id = 2
        mock_task.assigned_to = 3
        mock_task.project_id = 4
        mock_task.phase_id = 5
        mock_task.depends_on = 6
        mock_task.created_by = 7
        mock_task.scheduled_date = None
        mock_task.waiting_for = None
        mock_task.follow_up_date = None
        mock_task.created_at = datetime.now(timezone.utc)
        mock_task.updated_at = datetime.now(timezone.utc)
        mock_task.is_recurring = False
        mock_task.recurrence_pattern = None
        mock_task.recurrence_day = None
        mock_task.recurrence_end_date = None
        mock_task.recurring_parent_id = None
        mock_task.link_url = None
        mock_task.checklist_items = [MagicMock(), MagicMock()]
        # Set up relationships
        mock_task.client = MagicMock()
        mock_task.client.configure_mock(name="Acme Corp")
        mock_task.category = MagicMock()
        mock_task.category.configure_mock(name="Dev")
        mock_task.assigned_user = MagicMock(full_name="John Doe")
        mock_task.project = MagicMock()
        mock_task.project.configure_mock(name="Website")
        mock_task.phase = MagicMock()
        mock_task.phase.configure_mock(name="Phase 1")
        mock_task.dependency = MagicMock(title="Prereq task")
        mock_task.creator = MagicMock(full_name="Jane Admin")
        mock_task.recurring_parent = None

        result = _task_to_response(mock_task)
        assert result.client_name == "Acme Corp"
        assert result.category_name == "Dev"
        assert result.assigned_user_name == "John Doe"
        assert result.project_name == "Website"
        assert result.phase_name == "Phase 1"
        assert result.dependency_title == "Prereq task"
        assert result.created_by_name == "Jane Admin"
        assert result.checklist_count == 2

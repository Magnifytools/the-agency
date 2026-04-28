"""Regression tests for task creation 500 errors.

These tests verify that _task_to_response handles missing/null
relationships gracefully instead of crashing with AttributeError.
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from backend.db.models import Task, TaskStatus, TaskPriority


class TestTaskToResponse:
    def test_task_with_no_relationships(self):
        """A task with all relationships as None should not crash."""
        from backend.api.routes.tasks import _task_to_response

        task = MagicMock(spec=Task)
        task.id = 1
        task.title = "Test task"
        task.description = None
        task.status = TaskStatus.pending
        task.priority = TaskPriority.medium
        task.estimated_minutes = None
        task.actual_minutes = None
        task.due_date = None
        task.client_id = None
        task.category_id = None
        task.assigned_to = None
        task.project_id = None
        task.phase_id = None
        task.depends_on = None
        task.created_by = None
        task.scheduled_date = None
        task.waiting_for = None
        task.follow_up_date = None
        task.created_at = datetime.now()
        task.updated_at = datetime.now()
        task.is_recurring = False
        task.recurrence_pattern = None
        task.recurrence_day = None
        task.recurrence_end_date = None
        task.recurring_parent_id = None
        task.link_url = None
        # All relationships are None
        task.client = None
        task.category = None
        task.assigned_user = None
        task.project = None
        task.phase = None
        task.dependency = None
        task.creator = None
        task.recurring_parent = None
        task.checklist_items = []

        result = _task_to_response(task)

        assert result.id == 1
        assert result.client_name is None
        assert result.project_name is None
        assert result.assigned_user_name is None
        assert result.created_by_name is None

    def test_task_with_broken_relationship_access(self):
        """If a relationship raises on attribute access, should return None."""
        from backend.api.routes.tasks import _task_to_response

        task = MagicMock(spec=Task)
        task.id = 2
        task.title = "Broken rels"
        task.description = None
        task.status = TaskStatus.pending
        task.priority = TaskPriority.medium
        task.estimated_minutes = 60
        task.actual_minutes = 30
        task.due_date = None
        task.client_id = 99
        task.category_id = None
        task.assigned_to = 1
        task.project_id = None
        task.phase_id = None
        task.depends_on = None
        task.created_by = 1
        task.scheduled_date = None
        task.waiting_for = None
        task.follow_up_date = None
        task.created_at = datetime.now()
        task.updated_at = datetime.now()
        task.is_recurring = False
        task.recurrence_pattern = None
        task.recurrence_day = None
        task.recurrence_end_date = None
        task.recurring_parent_id = None
        task.link_url = None

        # Simulate a broken relationship where accessing .name raises
        class BrokenClient:
            @property
            def name(self):
                raise RuntimeError("detached instance")

        task.client = BrokenClient()
        task.category = None
        task.assigned_user = None
        task.project = None
        task.phase = None
        task.dependency = None
        task.creator = None
        task.recurring_parent = None
        task.checklist_items = None

        # _safe_attr should catch the error
        result = _task_to_response(task)
        assert result.id == 2
        assert result.client_name is None
        assert result.checklist_count == 0

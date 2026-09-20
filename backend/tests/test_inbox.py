"""Regression tests for inbox endpoints.

Covers:
- List inbox notes → 200
- Convert note to task (note not found in mock DB) → 404
- Create inbox note without required field (empty text) → 400
- _to_response handles null relationships gracefully
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock


@pytest.mark.asyncio
class TestInboxList:
    """GET /api/inbox"""

    async def test_list_notes_returns_200(self, admin_client):
        resp = await admin_client.get("/api/inbox")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
class TestInboxCount:
    """GET /api/inbox/count"""

    async def test_inbox_count_returns_200(self, admin_client):
        resp = await admin_client.get("/api/inbox/count")
        assert resp.status_code == 200
        assert "count" in resp.json()


@pytest.mark.asyncio
class TestConvertToTask:
    """POST /api/inbox/{note_id}/convert-to-task"""

    async def test_convert_nonexistent_note_returns_404(self, admin_client):
        resp = await admin_client.post(
            "/api/inbox/9999/convert-to-task",
            json={"title": "New task", "client_id": 1},
        )
        # Note not found in mock DB → 404
        assert resp.status_code == 404

    async def test_convert_without_body_nonexistent_note(self, admin_client):
        resp = await admin_client.post(
            "/api/inbox/9999/convert-to-task",
            json={},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestInboxCreate:
    """POST /api/inbox"""

    async def test_create_note_empty_text_returns_400(self, admin_client):
        resp = await admin_client.post(
            "/api/inbox",
            json={"raw_text": "   "},
        )
        # Empty text after strip → 400
        assert resp.status_code == 400


class TestInboxToResponse:
    """Test _to_response handles null relationships without crashing."""

    def test_null_project_and_client(self):
        from backend.api.routes.inbox import _to_response

        mock_note = MagicMock()
        mock_note.id = 1
        mock_note.user_id = 1
        mock_note.raw_text = "Test note"
        mock_note.source = "dashboard"
        mock_note.status = "pending"
        mock_note.project_id = None
        mock_note.client_id = None
        mock_note.resolved_as = None
        mock_note.resolved_entity_id = None
        mock_note.ai_suggestion = None
        mock_note.classification_error_code = None
        mock_note.classification_next_attempt_at = None
        mock_note.link_url = None
        mock_note.attachments = []
        mock_note.created_at = datetime.now(timezone.utc)
        mock_note.updated_at = datetime.now(timezone.utc)
        # Simulate missing relationships
        mock_note.project = None
        mock_note.client = None

        result = _to_response(mock_note)
        assert result.project_name is None
        assert result.client_name is None

    def test_with_project_and_client(self):
        from backend.api.routes.inbox import _to_response

        mock_note = MagicMock()
        mock_note.id = 2
        mock_note.user_id = 1
        mock_note.raw_text = "Test with relations"
        mock_note.source = "dashboard"
        mock_note.status = "classified"
        mock_note.project_id = 10
        mock_note.client_id = 5
        mock_note.resolved_as = None
        mock_note.resolved_entity_id = None
        mock_note.ai_suggestion = None
        mock_note.classification_error_code = None
        mock_note.classification_next_attempt_at = None
        mock_note.link_url = None
        mock_note.attachments = []
        mock_note.created_at = datetime.now(timezone.utc)
        mock_note.updated_at = datetime.now(timezone.utc)
        mock_note.project = MagicMock()
        mock_note.project.configure_mock(name="Project A")
        mock_note.client = MagicMock()
        mock_note.client.configure_mock(name="Client X")

        result = _to_response(mock_note)
        assert result.project_name == "Project A"
        assert result.client_name == "Client X"

    def test_suggestion_is_hidden_after_required_permission_is_revoked(self):
        from backend.api.routes.inbox import _to_response

        note = MagicMock()
        note.id = note.user_id = 1
        note.raw_text = "Sensitive context"
        note.source = "dashboard"
        note.status = "classified"
        note.project_id = note.client_id = None
        note.project = note.client = None
        note.resolved_as = note.resolved_entity_id = None
        note.ai_suggestion = {
            "suggested_project": None,
            "suggested_client": {"id": 9, "name": "Secret Client", "confidence": 1},
            "suggested_action": "create_task",
            "suggested_title": "Secret Client follow-up",
            "suggested_priority": "medium",
            "reasoning": "Mentions Secret Client",
            "_context_modules": ["projects", "clients"],
        }
        note.classification_error_code = None
        note.classification_next_attempt_at = None
        note.link_url = None
        note.attachments = []
        note.created_at = note.updated_at = datetime.now(timezone.utc)
        user = MagicMock()
        user.role.value = "member"
        permission = MagicMock(module="projects", can_read=True)
        user.permissions = [permission]

        result = _to_response(note, user)

        assert result.ai_suggestion is None

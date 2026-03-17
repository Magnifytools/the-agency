"""Regression tests for digest endpoints.

Covers:
- List digests → 200
- GET nonexistent digest → 404
- DELETE nonexistent digest → 404
- _to_response handles null client/creator
- _to_response handles malformed content
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from datetime import date, datetime, timezone

from backend.db.models import DigestStatus, DigestTone

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
class TestDigestsList:
    """GET /api/digests"""

    async def test_list_digests_returns_200(self, admin_client):
        resp = await admin_client.get("/api/digests")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_with_client_filter(self, admin_client):
        resp = await admin_client.get("/api/digests", params={"client_id": 1})
        assert resp.status_code == 200

    async def test_list_with_status_filter(self, admin_client):
        resp = await admin_client.get("/api/digests", params={"status": "draft"})
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestDigestsGet:
    """GET /api/digests/{id}"""

    async def test_get_nonexistent_digest(self, admin_client):
        resp = await admin_client.get("/api/digests/9999")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestDigestsDelete:
    """DELETE /api/digests/{id}"""

    async def test_delete_nonexistent_digest(self, admin_client):
        resp = await admin_client.delete("/api/digests/9999")
        assert resp.status_code == 404


class TestDigestsToResponse:
    """Test _to_response handles various data shapes."""

    def test_with_valid_content(self):
        from backend.api.routes.digests import _to_response

        mock_digest = MagicMock()
        mock_digest.id = 1
        mock_digest.client_id = 10
        mock_digest.client = MagicMock()
        mock_digest.client.configure_mock(name="Acme Corp")
        mock_digest.period_start = date(2025, 6, 1)
        mock_digest.period_end = date(2025, 6, 7)
        mock_digest.status = DigestStatus.draft
        mock_digest.tone = DigestTone.cercano
        mock_digest.content = {
            "greeting": "Hola",
            "summary": "Great week",
            "highlights": ["Task A done", "Task B done"],
            "metrics": {},
            "next_steps": ["Continue C"],
            "closing": "Saludos",
        }
        mock_digest.raw_context = {"tasks": []}
        mock_digest.generated_at = None
        mock_digest.edited_at = None
        mock_digest.created_by = 1
        mock_digest.creator = MagicMock(full_name="Admin")
        mock_digest.created_at = _NOW
        mock_digest.updated_at = _NOW

        result = _to_response(mock_digest)
        assert result.id == 1
        assert result.client_name == "Acme Corp"
        assert result.creator_name == "Admin"

    def test_with_null_client_and_creator(self):
        from backend.api.routes.digests import _to_response

        mock_digest = MagicMock()
        mock_digest.id = 2
        mock_digest.client_id = 10
        mock_digest.client = None
        mock_digest.period_start = date(2025, 6, 1)
        mock_digest.period_end = date(2025, 6, 7)
        mock_digest.status = DigestStatus.draft
        mock_digest.tone = DigestTone.cercano
        mock_digest.content = None
        mock_digest.raw_context = None
        mock_digest.generated_at = None
        mock_digest.edited_at = None
        mock_digest.created_by = 1
        mock_digest.creator = None
        mock_digest.created_at = _NOW
        mock_digest.updated_at = _NOW

        result = _to_response(mock_digest)
        assert result.client_name is None
        assert result.creator_name is None
        assert result.content is None

    def test_with_malformed_content(self):
        from backend.api.routes.digests import _to_response

        mock_digest = MagicMock()
        mock_digest.id = 3
        mock_digest.client_id = 10
        mock_digest.client = MagicMock()
        mock_digest.client.configure_mock(name="Test")
        mock_digest.period_start = date(2025, 6, 1)
        mock_digest.period_end = date(2025, 6, 7)
        mock_digest.status = DigestStatus.draft
        mock_digest.tone = DigestTone.cercano
        mock_digest.content = {"not_valid": True}
        mock_digest.raw_context = {}
        mock_digest.generated_at = None
        mock_digest.edited_at = None
        mock_digest.created_by = 1
        mock_digest.creator = MagicMock(full_name="Test")
        mock_digest.created_at = _NOW
        mock_digest.updated_at = _NOW

        # Should not crash — content may default to empty rather than None
        result = _to_response(mock_digest)
        assert result is not None

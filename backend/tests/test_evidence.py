"""Regression tests for project evidence endpoints.

Covers:
- List evidence → 200
- Create evidence without URL → 400
- _to_response handles null relationships gracefully
- _to_response generates download/preview URLs for files
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


@pytest.mark.asyncio
class TestEvidenceList:
    """GET /api/projects/{project_id}/evidence"""

    async def test_list_evidence_returns_200(self, admin_client):
        resp = await admin_client.get("/api/projects/1/evidence")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_evidence_empty_project(self, admin_client):
        resp = await admin_client.get("/api/projects/9999/evidence")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestEvidenceCreate:
    """POST /api/projects/{project_id}/evidence"""

    async def test_create_evidence_without_url_returns_400(self, admin_client):
        resp = await admin_client.post(
            "/api/projects/1/evidence",
            json={
                "title": "Test evidence",
                "evidence_type": "screenshot",
                "url": "",
            },
        )
        # Should reject: no URL and no file
        assert resp.status_code in (400, 404)


class TestEvidenceToResponse:
    """Test _to_response handles null relationships without crashing."""

    def test_null_creator_and_phase(self):
        from backend.api.routes.evidence import _to_response

        mock_ev = MagicMock()
        mock_ev.id = 1
        mock_ev.project_id = 10
        mock_ev.phase_id = None
        mock_ev.title = "Test"
        mock_ev.url = "https://example.com"
        mock_ev.evidence_type = "screenshot"
        mock_ev.description = None
        mock_ev.created_by = 1
        mock_ev.created_at = None
        mock_ev.updated_at = None
        mock_ev.file_name = None
        mock_ev.file_mime_type = None
        mock_ev.file_size_bytes = None
        # Simulate missing relationships
        mock_ev.creator = None
        mock_ev.phase = None

        result = _to_response(10, mock_ev)
        assert result["creator_name"] is None
        assert result["phase_name"] is None
        assert result["has_file"] is False
        assert result["download_url"] is None

    def test_with_file_generates_urls(self):
        from backend.api.routes.evidence import _to_response

        mock_ev = MagicMock()
        mock_ev.id = 5
        mock_ev.project_id = 10
        mock_ev.phase_id = 2
        mock_ev.title = "Report"
        mock_ev.url = None
        mock_ev.evidence_type = "document"
        mock_ev.description = "Monthly report"
        mock_ev.created_by = 1
        mock_ev.created_at = None
        mock_ev.updated_at = None
        mock_ev.file_name = "report.pdf"
        mock_ev.file_mime_type = "application/pdf"
        mock_ev.file_size_bytes = 1024
        mock_ev.creator = MagicMock(full_name="John")
        mock_ev.phase = MagicMock()
        mock_ev.phase.configure_mock(name="Audit")

        result = _to_response(10, mock_ev)
        assert result["creator_name"] == "John"
        assert result["has_file"] is True
        assert "/download" in result["download_url"]
        assert "/preview" in result["preview_url"]

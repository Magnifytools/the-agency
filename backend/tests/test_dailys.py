"""Regression tests for daily updates endpoints.

Covers:
- List dailys → 200
- GET nonexistent daily → 404
- Invalid date filter → 400
- Prefill endpoint
- DELETE nonexistent → 404
- _to_response with null/malformed data
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from backend.db.models import DailyUpdateStatus

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
class TestDailysList:
    """GET /api/dailys"""

    async def test_list_dailys_returns_200(self, admin_client):
        resp = await admin_client.get("/api/dailys")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_with_date_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/dailys",
            params={"date_from": "2025-01-01", "date_to": "2025-12-31"},
        )
        assert resp.status_code == 200

    async def test_invalid_date_format(self, admin_client):
        resp = await admin_client.get(
            "/api/dailys", params={"date_from": "not-a-date"}
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestDailysGet:
    """GET /api/dailys/{id}"""

    async def test_get_nonexistent_daily(self, admin_client):
        resp = await admin_client.get("/api/dailys/9999")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestDailysPrefill:
    """GET /api/dailys/prefill"""

    async def test_prefill_returns_text(self, admin_client):
        resp = await admin_client.get("/api/dailys/prefill")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "completed_count" in data
        assert "worked_on_count" in data


@pytest.mark.asyncio
class TestDailysDelete:
    """DELETE /api/dailys/{id}"""

    async def test_delete_nonexistent_daily(self, admin_client):
        resp = await admin_client.delete("/api/dailys/9999")
        assert resp.status_code == 404


class TestDailysToResponse:
    """Test _to_response handles various data shapes."""

    def test_with_valid_parsed_data(self):
        from backend.api.routes.dailys import _to_response

        mock_daily = MagicMock()
        mock_daily.id = 1
        mock_daily.user_id = 1
        mock_daily.user = MagicMock(full_name="David")
        mock_daily.date = "2025-06-01"
        mock_daily.raw_text = "Worked on stuff"
        mock_daily.parsed_data = {
            "tasks": [
                {"client": "Acme", "description": "SEO audit", "hours": 2.0}
            ],
            "blockers": [],
            "summary": "Good day",
        }
        mock_daily.status = DailyUpdateStatus.draft
        mock_daily.discord_sent_at = None
        mock_daily.created_at = _NOW
        mock_daily.updated_at = _NOW

        result = _to_response(mock_daily)
        assert result.user_name == "David"
        assert result.status == DailyUpdateStatus.draft

    def test_with_null_user(self):
        from backend.api.routes.dailys import _to_response

        mock_daily = MagicMock()
        mock_daily.id = 2
        mock_daily.user_id = 1
        mock_daily.user = None
        mock_daily.date = "2025-06-01"
        mock_daily.raw_text = "Test"
        mock_daily.parsed_data = None
        mock_daily.status = DailyUpdateStatus.draft
        mock_daily.discord_sent_at = None
        mock_daily.created_at = _NOW
        mock_daily.updated_at = _NOW

        result = _to_response(mock_daily)
        assert result.user_name is None
        assert result.parsed_data is None

    def test_with_malformed_parsed_data(self):
        from backend.api.routes.dailys import _to_response

        mock_daily = MagicMock()
        mock_daily.id = 3
        mock_daily.user_id = 1
        mock_daily.user = MagicMock(full_name="Test")
        mock_daily.date = "2025-06-01"
        mock_daily.raw_text = "Test"
        mock_daily.parsed_data = {"invalid": "structure"}
        mock_daily.status = DailyUpdateStatus.draft
        mock_daily.discord_sent_at = None
        mock_daily.created_at = _NOW
        mock_daily.updated_at = _NOW

        # Should not crash — returns None for parsed_data if schema doesn't match
        result = _to_response(mock_daily)
        assert result is not None

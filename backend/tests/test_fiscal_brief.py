"""Tests for fiscal brief service and advisor AI endpoints."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import date

from backend.services.fiscal_brief_service import _quarter_dates, _format_list


class TestQuarterDates:
    def test_q1(self):
        start, end = _quarter_dates(2026, "Q1")
        assert start == date(2026, 1, 1)
        assert end == date(2026, 3, 31)

    def test_q2(self):
        start, end = _quarter_dates(2026, "Q2")
        assert start == date(2026, 4, 1)
        assert end == date(2026, 6, 30)

    def test_q3(self):
        start, end = _quarter_dates(2026, "Q3")
        assert start == date(2026, 7, 1)
        assert end == date(2026, 9, 30)

    def test_q4(self):
        start, end = _quarter_dates(2026, "Q4")
        assert start == date(2026, 10, 1)
        assert end == date(2026, 12, 31)


class TestFormatList:
    def test_empty_returns_ninguno(self):
        assert _format_list([], "{name}") == "(ninguno)"

    def test_formats_items(self):
        items = [{"name": "A", "total": 100}, {"name": "B", "total": 200}]
        result = _format_list(items, "- {name}: {total}")
        assert "- A: 100" in result
        assert "- B: 200" in result


@pytest.mark.asyncio
class TestGenerateBriefEndpoint:
    async def test_invalid_quarter_returns_422(self, admin_client):
        resp = await admin_client.post(
            "/api/finance/advisor/generate-brief?year=2026&quarter=Q5"
        )
        assert resp.status_code == 422

    async def test_valid_quarter_format(self, admin_client):
        # Validate Q1-Q4 pattern works, Q5 doesn't
        resp_ok = await admin_client.post(
            "/api/finance/advisor/generate-brief?year=2026&quarter=Q1"
        )
        # Route accepts params (may fail at AI/DB level)
        assert resp_ok.status_code != 422


@pytest.mark.asyncio
class TestGenerateInsightsEndpoint:
    async def test_endpoint_exists(self, admin_client):
        resp = await admin_client.post("/api/finance/advisor/generate-insights")
        # Will fail at Claude API, but route exists
        assert resp.status_code not in (404, 422, 405)

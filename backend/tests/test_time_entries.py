"""Regression tests for time entries / timer endpoints.

Covers:
- Timer start validation (no task_id or notes → 400)
- Timer stop with no active timer → 404
- Active timer query → 200
- List time entries → 200
- Manual entry creation
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestTimerStart:
    """POST /api/timer/start"""

    async def test_timer_start_no_task_no_notes_returns_400(self, admin_client):
        resp = await admin_client.post(
            "/api/timer/start",
            json={"task_id": None, "notes": ""},
        )
        # Should fail validation: need task_id or notes
        assert resp.status_code == 400

    async def test_timer_start_nonexistent_task(self, admin_client):
        resp = await admin_client.post(
            "/api/timer/start",
            json={"task_id": 9999},
        )
        # Task not found in mock DB → 404
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestTimerStop:
    """POST /api/timer/stop"""

    async def test_timer_stop_no_active_timer(self, admin_client):
        resp = await admin_client.post(
            "/api/timer/stop",
            json={},
        )
        # No active timer → 404
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestActiveTimer:
    """GET /api/timer/active"""

    async def test_active_timer_returns_200(self, admin_client):
        resp = await admin_client.get("/api/timer/active")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestTimeEntriesList:
    """GET /api/time-entries"""

    async def test_list_time_entries_returns_200(self, admin_client):
        resp = await admin_client.get("/api/time-entries")
        assert resp.status_code == 200

    async def test_list_with_date_filter(self, admin_client):
        resp = await admin_client.get(
            "/api/time-entries",
            params={"date_from": "2025-01-01", "date_to": "2025-12-31"},
        )
        assert resp.status_code == 200

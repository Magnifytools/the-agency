"""Integration tests for timesheet money/total correctness (REAL Postgres DB).

Covers the arithmetic the mocked suite can't verify because it never runs SQL:

  * A manually created time entry persists with the exact minutes.
  * The weekly timesheet aggregates minutes into the correct day bucket and
    total.
  * The by-client report computes ``cost_eur = minutes * hourly_rate / 60`` and
    sums totals correctly across multiple entries.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from backend.db.models import Client, Task, TimeEntry


async def _make_client_and_task(db_session, *, client_name="Cliente Test"):
    client = Client(name=client_name)
    db_session.add(client)
    await db_session.flush()
    task = Task(title="Tarea facturable", client_id=client.id)
    db_session.add(task)
    await db_session.flush()
    return client, task


@pytest.mark.asyncio
async def test_create_time_entry_persists_minutes(admin_client, db_session):
    _, task = await _make_client_and_task(db_session)

    resp = await admin_client.post(
        "/api/time-entries",
        json={"minutes": 90, "task_id": task.id, "notes": "trabajo real"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["minutes"] == 90
    assert body["task_id"] == task.id

    row = (
        await db_session.execute(
            select(TimeEntry).where(TimeEntry.id == body["id"])
        )
    ).scalar_one()
    assert row.minutes == 90
    assert row.user_id == admin_client.test_user.id


@pytest.mark.asyncio
async def test_create_time_entry_rejects_nonpositive(admin_client, db_session):
    _, task = await _make_client_and_task(db_session, client_name="C2")
    resp = await admin_client.post(
        "/api/time-entries", json={"minutes": 0, "task_id": task.id}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_by_client_report_cost_is_correct(admin_client, admin_user, db_session):
    """cost_eur must equal minutes * hourly_rate / 60, summed across entries.

    admin_user.hourly_rate is 40.0 (set by the fixture). Two entries of 60 and
    30 minutes -> 90 minutes -> 90 * 40 / 60 = 60.00 EUR.
    """
    client, task = await _make_client_and_task(db_session, client_name="Facturable SL")

    for mins in (60, 30):
        r = await admin_client.post(
            "/api/time-entries", json={"minutes": mins, "task_id": task.id}
        )
        assert r.status_code == 201, r.text

    resp = await admin_client.get("/api/time-entries/by-client")
    assert resp.status_code == 200, resp.text
    reports = resp.json()

    mine = next((c for c in reports if c["client_id"] == client.id), None)
    assert mine is not None, f"client {client.id} missing from {reports}"
    assert mine["total_minutes"] == 90
    # 90 min @ 40 EUR/h = 60.00 EUR
    assert mine["cost_eur"] == pytest.approx(60.0, abs=0.01)
    assert mine["entries_count"] == 2

    # Team breakdown attributes the cost to the admin user.
    team = mine["team_breakdown"]
    assert len(team) == 1
    assert team[0]["user_id"] == admin_user.id
    assert team[0]["total_minutes"] == 90
    assert team[0]["cost_eur"] == pytest.approx(60.0, abs=0.01)


@pytest.mark.asyncio
async def test_weekly_timesheet_totals(admin_client, admin_user, db_session):
    """Two entries on the same day roll up into that day's bucket and the total."""
    client, task = await _make_client_and_task(db_session, client_name="Semanal SA")

    # Use a fixed date so we can assert the exact day bucket.
    fixed = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)  # a Monday
    for mins in (45, 15):
        entry = TimeEntry(
            minutes=mins,
            task_id=task.id,
            user_id=admin_user.id,
            date=fixed.replace(tzinfo=None),
        )
        db_session.add(entry)
    await db_session.flush()

    resp = await admin_client.get(
        "/api/time-entries/weekly", params={"week_start": "2026-06-15"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["week_start"] == "2026-06-15"

    me = next((u for u in data["users"] if u["user_id"] == admin_user.id), None)
    assert me is not None, data["users"]
    assert me["total_minutes"] == 60
    assert me["daily_minutes"]["2026-06-15"] == 60

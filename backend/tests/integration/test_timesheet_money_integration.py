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


@pytest.mark.asyncio
async def test_weekly_timesheet_keeps_manual_civil_date_but_converts_timer_instant(
    admin_client, admin_user, db_session
):
    """The overloaded legacy date column has two deliberate meanings."""
    _, task = await _make_client_and_task(db_session, client_name="Frontera Madrid")
    db_session.add_all([
        TimeEntry(
            minutes=20,
            task_id=task.id,
            user_id=admin_user.id,
            # Explicit manual Sunday stays Sunday and is outside this week.
            date=datetime(2026, 6, 14, 23, 30),
        ),
        TimeEntry(
            minutes=30,
            task_id=task.id,
            user_id=admin_user.id,
            # Timer instant Sunday 22:30 UTC is Monday 00:30 in Madrid.
            date=datetime(2026, 6, 14, 22, 30),
            started_at=datetime(2026, 6, 14, 22, 30),
        ),
    ])
    await db_session.flush()

    response = await admin_client.get(
        "/api/time-entries/weekly", params={"week_start": "2026-06-15"}
    )
    assert response.status_code == 200, response.text
    me = next(user for user in response.json()["users"] if user["user_id"] == admin_user.id)
    assert me["daily_minutes"]["2026-06-15"] == 30
    assert me["total_minutes"] == 30


@pytest.mark.asyncio
async def test_date_range_keeps_manual_day_and_timer_instant_semantics(
    admin_client, admin_user, db_session
):
    _, task = await _make_client_and_task(db_session, client_name="Rango mixto")
    entries = [
        TimeEntry(minutes=10, task_id=task.id, user_id=admin_user.id, date=datetime(2026, 9, 16, 23)),
        TimeEntry(minutes=20, task_id=task.id, user_id=admin_user.id, date=datetime(2026, 9, 17)),
        TimeEntry(
            minutes=30, task_id=task.id, user_id=admin_user.id,
            date=datetime(2026, 9, 16, 22, 30), started_at=datetime(2026, 9, 16, 22, 30),
        ),
    ]
    db_session.add_all(entries)
    await db_session.flush()

    response = await admin_client.get("/api/time-entries", params={
        "date_from": "2026-09-16T22:00:00Z",
        "date_to": "2026-09-17T21:59:59.999Z",
    })
    assert response.status_code == 200, response.text
    returned_ids = {row["id"] for row in response.json()}
    assert entries[0].id not in returned_ids
    assert {entries[1].id, entries[2].id} <= returned_ids

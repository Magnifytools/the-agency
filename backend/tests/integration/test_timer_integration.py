"""Integration tests for the time-tracking timer against a REAL Postgres DB.

These exercise the highest-risk timer invariant the mocked suite can't see:
*there is never more than one active timer (minutes IS NULL) per user*. That
invariant is enforced two ways and both are tested here:

  1. Application logic: ``POST /api/timer/start`` auto-stops any existing active
     timer before inserting the new one.
  2. Database backstop: the partial unique index ``uq_time_entries_active_timer``
     (created by ``_ensure_indexes_v11``) makes a *concurrent/duplicate* insert
     of a second active row fail with a unique violation — caught by the route
     and surfaced as 409, and provably impossible at the DB level.

Plus money/magnitude correctness: a stopped timer must compute the elapsed
minutes with the right sign and magnitude.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import func, select

from backend.db.models import TimeEntry


async def _count_active_timers(db_session, user_id: int) -> int:
    result = await db_session.execute(
        select(func.count())
        .select_from(TimeEntry)
        .where(TimeEntry.user_id == user_id, TimeEntry.minutes.is_(None))
    )
    return int(result.scalar() or 0)


@pytest.mark.asyncio
async def test_start_timer_creates_single_active_row(admin_client, db_session):
    """Starting a timer creates exactly one active (minutes IS NULL) row."""
    user_id = admin_client.test_user.id

    resp = await admin_client.post("/api/timer/start", json={"notes": "work block"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["task_id"] is None
    assert body["started_at"] is not None

    assert await _count_active_timers(db_session, user_id) == 1

    # get-active reports it
    active = await admin_client.get("/api/timer/active")
    assert active.status_code == 200, active.text
    assert active.json() is not None
    assert active.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_starting_second_timer_autostops_first(admin_client, db_session):
    """Starting a 2nd timer while one is active must NOT leave two active rows.

    The route auto-stops the previous one, so afterwards there is exactly one
    active timer and the first row is now a completed entry (minutes IS NOT NULL).
    """
    user_id = admin_client.test_user.id

    first = await admin_client.post("/api/timer/start", json={"notes": "first"})
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    second = await admin_client.post("/api/timer/start", json={"notes": "second"})
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assert second_id != first_id

    # INVARIANT: never more than one active timer per user
    assert await _count_active_timers(db_session, user_id) == 1

    # The first entry is now closed (auto-stopped) with a real minutes value
    row = (
        await db_session.execute(select(TimeEntry).where(TimeEntry.id == first_id))
    ).scalar_one()
    assert row.minutes is not None
    assert row.minutes >= 1  # stop clamps to a minimum of 1

    # The second entry is the active one
    row2 = (
        await db_session.execute(select(TimeEntry).where(TimeEntry.id == second_id))
    ).scalar_one()
    assert row2.minutes is None


@pytest.mark.asyncio
async def test_partial_unique_index_blocks_duplicate_active_timer(
    admin_client, admin_user, db_session
):
    """The DB-level backstop: a *direct* second active insert must be rejected.

    This is the concurrent/duplicate case the route's read-then-act logic can't
    prevent on its own — it relies on ``uq_time_entries_active_timer``. We start
    one timer through the API, then try to insert a second active row directly
    (simulating a racing request that slipped past the app check) and assert the
    partial unique index raises.
    """
    from sqlalchemy.exc import IntegrityError

    user_id = admin_user.id

    started = await admin_client.post("/api/timer/start", json={"notes": "held"})
    assert started.status_code == 201, started.text
    assert await _count_active_timers(db_session, user_id) == 1

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dup = TimeEntry(
        task_id=None,
        user_id=user_id,
        started_at=now,
        date=now,
        notes="racing duplicate",
        minutes=None,  # active
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    # The failed statement poisons the savepoint; roll back to a clean state.
    await db_session.rollback()


@pytest.mark.asyncio
async def test_index_exists_on_test_db(db_session):
    """Explicitly assert the partial unique index was created by the migration."""
    from sqlalchemy import text

    row = await db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_time_entries_active_timer'"
        )
    )
    indexdef = row.scalar_one_or_none()
    assert indexdef is not None, "uq_time_entries_active_timer index is missing"
    assert "UNIQUE" in indexdef.upper()
    assert "time_entries" in indexdef
    # Partial: only over active rows (minutes IS NULL)
    assert "minutes IS NULL" in indexdef


@pytest.mark.asyncio
async def test_stop_timer_computes_elapsed_minutes(admin_client, db_session):
    """Stopping a timer computes positive elapsed minutes of the right magnitude.

    We back-date the active row's ``started_at`` to 25 minutes ago, then stop and
    assert the computed ``minutes`` is ~25 (sign positive, magnitude correct).
    """
    user_id = admin_client.test_user.id

    started = await admin_client.post("/api/timer/start", json={"notes": "billable"})
    assert started.status_code == 201, started.text
    entry_id = started.json()["id"]

    # Back-date the start by 25 minutes (naive UTC to match the column type).
    twenty_five_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=25)
    row = (
        await db_session.execute(select(TimeEntry).where(TimeEntry.id == entry_id))
    ).scalar_one()
    row.started_at = twenty_five_ago
    await db_session.flush()

    stopped = await admin_client.post("/api/timer/stop", json={})
    assert stopped.status_code == 200, stopped.text
    minutes = stopped.json()["minutes"]

    # Magnitude: ~25 minutes, allow a small wall-clock delta. Sign: positive.
    assert minutes > 0
    assert 24 <= minutes <= 26, f"expected ~25 minutes, got {minutes}"

    # No active timer remains
    assert await _count_active_timers(db_session, user_id) == 0


@pytest.mark.asyncio
async def test_stop_with_no_active_timer_404(admin_client):
    resp = await admin_client.post("/api/timer/stop", json={})
    assert resp.status_code == 404
    assert "activo" in resp.json()["detail"].lower()

"""PostgreSQL boundaries for manual civil dates and timer UTC instants."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from backend.db.models import TimeEntry
from backend.services.time_entry_dates import time_entry_civil_period
from backend.services.time_entry_dates import manual_time_entry_date


pytestmark = pytest.mark.integration


def test_default_manual_date_uses_madrid_day_after_utc_22_boundary():
    assert manual_time_entry_date(datetime(2026, 9, 17, 22, 30, tzinfo=timezone.utc)) == datetime(2026, 9, 18)


async def _entry(db, user_id: int, value: datetime, *, timer: bool) -> TimeEntry:
    entry = TimeEntry(
        user_id=user_id,
        minutes=5,
        date=value,
        started_at=value if timer else None,
    )
    db.add(entry)
    await db.flush()
    return entry


@pytest.mark.parametrize(
    ("start", "end", "inside", "outside"),
    [
        (
            date(2026, 9, 17), date(2026, 9, 18),
            [(datetime(2026, 9, 17), False), (datetime(2026, 9, 16, 22), True)],
            [(datetime(2026, 9, 16, 23), False), (datetime(2026, 9, 17, 22), True)],
        ),
        (
            date(2026, 9, 1), date(2026, 10, 1),
            [(datetime(2026, 9, 30, 23), False), (datetime(2026, 8, 31, 22), True)],
            [(datetime(2026, 8, 31, 23), False), (datetime(2026, 9, 30, 22), True)],
        ),
        (
            date(2026, 9, 14), date(2026, 9, 21),
            [(datetime(2026, 9, 20, 23), False), (datetime(2026, 9, 20, 21, 59), True)],
            [(datetime(2026, 9, 21), False), (datetime(2026, 9, 20, 22), True)],
        ),
    ],
)
async def test_civil_period_filters_manual_and_timer_cohorts(
    db_session, admin_user, start, end, inside, outside
):
    included = [await _entry(db_session, admin_user.id, value, timer=timer) for value, timer in inside]
    excluded = [await _entry(db_session, admin_user.id, value, timer=timer) for value, timer in outside]

    rows = (await db_session.execute(
        select(TimeEntry.id).where(time_entry_civil_period(start, end))
    )).scalars().all()

    assert {entry.id for entry in included} <= set(rows)
    assert not ({entry.id for entry in excluded} & set(rows))


async def test_manual_writers_default_to_business_day_and_preserve_explicit_date(
    admin_client, db_session, monkeypatch
):
    from backend.api.routes import tasks as tasks_route
    from backend.api.routes import time_entries as time_entries_route

    boundary_day = datetime(2026, 9, 18)
    monkeypatch.setattr(time_entries_route, "manual_time_entry_date", lambda: boundary_day)
    monkeypatch.setattr(tasks_route, "manual_time_entry_date", lambda: boundary_day)

    implicit = await admin_client.post("/api/time-entries", json={"minutes": 15})
    assert implicit.status_code == 201, implicit.text
    assert implicit.json()["date"] == "2026-09-18T00:00:00"

    explicit = await admin_client.post(
        "/api/time-entries",
        json={"minutes": 20, "date": "2026-08-03T12:34:00"},
    )
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["date"] == "2026-08-03T12:34:00"

    task = await admin_client.post(
        "/api/tasks", json={"title": "Ajuste manual civil", "actual_minutes": 25}
    )
    assert task.status_code == 201, task.text
    manual = (await db_session.execute(
        select(TimeEntry).where(
            TimeEntry.task_id == task.json()["id"],
            TimeEntry.notes == "[manual]",
        )
    )).scalar_one()
    assert manual.date == boundary_day

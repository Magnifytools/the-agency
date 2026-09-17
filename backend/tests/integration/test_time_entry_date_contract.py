"""PostgreSQL boundaries for manual civil dates and timer UTC instants."""
from datetime import date, datetime

import pytest
from sqlalchemy import select

from backend.db.models import TimeEntry
from backend.services.time_entry_dates import time_entry_civil_period


pytestmark = pytest.mark.integration


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

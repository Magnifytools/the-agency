"""SQL contract for the legacy dual-purpose ``TimeEntry.date`` column.

Manual entries store a user-selected civil date (``started_at IS NULL``).
Timer entries store a naive UTC instant (``started_at IS NOT NULL``). Readers
must filter each cohort with its own boundaries; the stored values are not
rewritten or reinterpreted.
"""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import and_, or_

from backend.db.models import TimeEntry
from backend.services.temporal import civil_day_utc_bounds


def time_entry_civil_period(start: date, end_exclusive: date):
    """Return a half-open SQL condition for ``[start, end_exclusive)``."""
    utc_start, _ = civil_day_utc_bounds(start)
    utc_end, _ = civil_day_utc_bounds(end_exclusive)
    civil_start = datetime.combine(start, time.min)
    civil_end = datetime.combine(end_exclusive, time.min)
    return or_(
        and_(
            TimeEntry.started_at.is_(None),
            TimeEntry.date >= civil_start,
            TimeEntry.date < civil_end,
        ),
        and_(
            TimeEntry.started_at.isnot(None),
            TimeEntry.date >= utc_start,
            TimeEntry.date < utc_end,
        ),
    )

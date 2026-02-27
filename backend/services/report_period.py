from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timezone
from typing import Optional, Tuple

MIN_REPORT_YEAR = 2000
MAX_REPORT_YEAR = 2100


def resolve_default_period(year: Optional[int], month: Optional[int]) -> Tuple[int, int]:
    now = datetime.now(timezone.utc)
    return year or now.year, month or now.month


def month_range_naive(year: int, month: int) -> Tuple[datetime, datetime]:
    """Return naive UTC datetimes for TIMESTAMP WITHOUT TIME ZONE columns."""
    _, last_day = monthrange(year, month)
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end

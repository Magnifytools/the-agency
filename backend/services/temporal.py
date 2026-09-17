"""Shared contract for civil dates and UTC instants.

Database ``DateTime`` columns are historically ``timestamp without time zone``.
New instants therefore remain naive UTC in storage, while API responses expose
an explicit UTC offset. Civil dates are never shifted through UTC.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.config import settings


def business_zone() -> ZoneInfo:
    return ZoneInfo(settings.AGENCY_TIMEZONE)


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def business_today(*, now: datetime | None = None) -> date:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(business_zone()).date()


def civil_day_utc_bounds(day: date) -> tuple[datetime, datetime]:
    """Return naive UTC ``[start, end)`` bounds for one business civil day."""
    zone = business_zone()
    start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


def civil_week_utc_bounds(day: date) -> tuple[datetime, datetime]:
    monday = day - timedelta(days=day.weekday())
    start, _ = civil_day_utc_bounds(monday)
    end, _ = civil_day_utc_bounds(monday + timedelta(days=7))
    return start, end


def as_utc_instant(value: datetime | None) -> datetime | None:
    """Attach UTC to legacy naive UTC or normalize an aware instant to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_isoformat(value: datetime | None) -> str | None:
    instant = as_utc_instant(value)
    if instant is None:
        return None
    return instant.isoformat().replace("+00:00", "Z")


def civil_date_isoformat(value: date | datetime | None) -> str | None:
    """Serialize the written calendar date without applying a timezone shift."""
    if value is None:
        return None
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()

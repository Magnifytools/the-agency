"""Compatibility boundary for the former daily-to-timesheet inference.

A daily is narrative input. It must never create real hours from an estimate,
fuzzy task match, or fallback duration. Callers that need to record time must
use the explicit time-entry routes with an exact task and duration.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession


async def create_time_entries_from_daily(
    db: AsyncSession,
    user_id: int,
    daily_date: date,
    parsed_data: dict,
) -> int:
    """Do not infer time entries from daily text; retained for old imports."""
    return 0

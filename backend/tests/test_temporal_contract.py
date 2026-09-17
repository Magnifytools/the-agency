"""Civil dates and instants remain distinct at API boundaries."""

from datetime import date, datetime, timezone

from backend.config import settings
from backend.core.modules import hidden_modules
from backend.db.models import TaskPriority, TaskStatus
from backend.schemas.task import TaskResponse
from backend.schemas.time_entry import ActiveTimerResponse, TimeEntryResponse
from backend.services.temporal import (
    business_today,
    civil_day_utc_bounds,
    civil_week_utc_bounds,
)


def test_madrid_dst_days_have_23_and_25_real_hours(monkeypatch):
    monkeypatch.setattr(settings, "AGENCY_TIMEZONE", "Europe/Madrid")

    spring_start, spring_end = civil_day_utc_bounds(date(2026, 3, 29))
    autumn_start, autumn_end = civil_day_utc_bounds(date(2026, 10, 25))

    assert spring_start == datetime(2026, 3, 28, 23)
    assert spring_end == datetime(2026, 3, 29, 22)
    assert (spring_end - spring_start).total_seconds() == 23 * 3600
    assert autumn_start == datetime(2026, 10, 24, 22)
    assert autumn_end == datetime(2026, 10, 25, 23)
    assert (autumn_end - autumn_start).total_seconds() == 25 * 3600


def test_madrid_midnight_and_week_bounds_are_half_open(monkeypatch):
    monkeypatch.setattr(settings, "AGENCY_TIMEZONE", "Europe/Madrid")
    instant = datetime(2026, 9, 17, 22, 30, tzinfo=timezone.utc)

    assert business_today(now=instant) == date(2026, 9, 18)
    day_start, day_end = civil_day_utc_bounds(date(2026, 9, 18))
    week_start, week_end = civil_week_utc_bounds(date(2026, 9, 18))
    assert day_start <= instant.replace(tzinfo=None) < day_end
    assert week_start == datetime(2026, 9, 13, 22)
    assert week_end == datetime(2026, 9, 20, 22)


def test_task_json_keeps_planning_dates_civil_and_completion_explicit_utc():
    task = TaskResponse(
        id=1,
        title="Contrato temporal",
        status=TaskStatus.completed,
        priority=TaskPriority.medium,
        start_date=datetime(2026, 9, 17),
        due_date=datetime(2026, 9, 18),
        created_at=datetime(2026, 9, 1, 8),
        updated_at=datetime(2026, 9, 18, 9),
        completed_at=datetime(2026, 9, 17, 22, 30),
    ).model_dump(mode="json")

    assert task["start_date"] == "2026-09-17"
    assert task["due_date"] == "2026-09-18"
    assert task["completed_at"] == "2026-09-17T22:30:00Z"


def test_timer_json_marks_legacy_naive_instants_as_utc_without_touching_entry_date():
    active = ActiveTimerResponse(id=1, started_at=datetime(2026, 9, 17, 22, 30))
    entry = TimeEntryResponse(
        id=1,
        started_at=datetime(2026, 9, 17, 22, 30),
        date=datetime(2026, 9, 17),
        user_id=2,
        created_at=datetime(2026, 9, 17, 22, 30),
        updated_at=datetime(2026, 9, 17, 22, 30),
    )

    assert active.model_dump(mode="json")["started_at"] == "2026-09-17T22:30:00Z"
    payload = entry.model_dump(mode="json")
    assert payload["started_at"] == "2026-09-17T22:30:00Z"
    assert payload["date"] == "2026-09-17T00:00:00"


async def test_app_config_exposes_the_single_business_timezone(admin_client):
    response = await admin_client.get("/api/config")
    assert response.status_code == 200
    assert response.json() == {
        "timezone": settings.AGENCY_TIMEZONE,
        "hidden_modules": sorted(hidden_modules()),
    }

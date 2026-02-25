from __future__ import annotations
from typing import Optional

from datetime import datetime, timezone, timedelta, date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models import TimeEntry, Task, User, UserRole
from backend.schemas.time_entry import (
    TimeEntryCreate,
    TimeEntryUpdate,
    TimeEntryResponse,
    TimerStartRequest,
    TimerStopRequest,
    ActiveTimerResponse,
)
from backend.api.deps import get_current_user, require_module

router = APIRouter(tags=["time-entries"])


def _entry_to_response(entry: TimeEntry) -> TimeEntryResponse:
    return TimeEntryResponse(
        id=entry.id,
        minutes=entry.minutes,
        started_at=entry.started_at,
        date=entry.date,
        notes=entry.notes,
        task_id=entry.task_id,
        user_id=entry.user_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        task_title=entry.task.title if entry.task else None,
        client_name=entry.task.client.name if entry.task and entry.task.client else None,
    )


# --- CRUD ---

@router.post("/api/time-entries", response_model=TimeEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_time_entry(
    body: TimeEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet", write=True)),
):
    entry = TimeEntry(
        minutes=body.minutes,
        task_id=body.task_id,
        user_id=current_user.id,
        notes=body.notes,
        date=body.date or datetime.utcnow(),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_to_response(entry)


@router.get("/api/time-entries", response_model=list[TimeEntryResponse])
async def list_time_entries(
    task_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet")),
):
    query = select(TimeEntry).where(TimeEntry.minutes.isnot(None))
    # F-05: members can only see their own time entries
    if current_user.role != UserRole.admin:
        query = query.where(TimeEntry.user_id == current_user.id)
    elif user_id is not None:
        query = query.where(TimeEntry.user_id == user_id)
    if task_id is not None:
        query = query.where(TimeEntry.task_id == task_id)
    if date_from is not None:
        query = query.where(TimeEntry.date >= date_from)
    if date_to is not None:
        query = query.where(TimeEntry.date <= date_to)
    query = query.order_by(TimeEntry.date.desc())
    result = await db.execute(query)
    return [_entry_to_response(e) for e in result.scalars().all()]


@router.get("/api/time-entries/weekly")
async def weekly_timesheet(
    week_start: Optional[date_type] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_module("timesheet")),
):
    today = datetime.now(timezone.utc).date()
    if week_start is None:
        week_start = today - timedelta(days=today.weekday())  # Monday
    start_dt = datetime.combine(week_start, datetime.min.time())
    end_dt = start_dt + timedelta(days=7)

    # Load users
    result = await db.execute(select(User).order_by(User.full_name))
    users = result.scalars().all()

    days = [(week_start + timedelta(days=i)) for i in range(7)]
    day_keys = [d.isoformat() for d in days]

    user_map = {}
    for u in users:
        user_map[u.id] = {
            "user_id": u.id,
            "full_name": u.full_name,
            "daily_minutes": {k: 0 for k in day_keys},
            "total_minutes": 0,
        }

    # Fetch time entries within range
    result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.minutes.isnot(None),
            TimeEntry.date >= start_dt,
            TimeEntry.date < end_dt,
        )
    )
    entries = result.scalars().all()

    for entry in entries:
        day_key = entry.date.date().isoformat()
        if entry.user_id in user_map and day_key in user_map[entry.user_id]["daily_minutes"]:
            user_map[entry.user_id]["daily_minutes"][day_key] += entry.minutes or 0
            user_map[entry.user_id]["total_minutes"] += entry.minutes or 0

    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "days": day_keys,
        "users": list(user_map.values()),
    }


@router.put("/api/time-entries/{entry_id}", response_model=TimeEntryResponse)
async def update_time_entry(
    entry_id: int,
    body: TimeEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet", write=True)),
):
    result = await db.execute(select(TimeEntry).where(TimeEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")
    # F-05: members can only edit their own entries
    if current_user.role != UserRole.admin and entry.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your time entry")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await db.commit()
    await db.refresh(entry)
    return _entry_to_response(entry)


@router.delete("/api/time-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_time_entry(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet", write=True)),
):
    result = await db.execute(select(TimeEntry).where(TimeEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found")
    # F-05: members can only delete their own entries
    if current_user.role != UserRole.admin and entry.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your time entry")
    await db.delete(entry)
    await db.commit()


# --- Timer ---

@router.post("/api/timer/start", response_model=ActiveTimerResponse, status_code=status.HTTP_201_CREATED)
async def start_timer(
    body: TimerStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet", write=True)),
):
    # Check no active timer for this user
    result = await db.execute(
        select(TimeEntry).where(
            and_(TimeEntry.user_id == current_user.id, TimeEntry.minutes.is_(None))
        )
    )
    active = result.scalar_one_or_none()
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un timer activo. Detén el actual antes de iniciar otro.",
        )
        
    if body.task_id is None and not body.notes:
        raise HTTPException(status_code=400, detail="Debes enviar un task_id o una nota")

    task = None
    if body.task_id is not None:
        # Verify task exists
        task_result = await db.execute(select(Task).where(Task.id == body.task_id))
        task = task_result.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

    now = datetime.utcnow()
    entry = TimeEntry(
        task_id=body.task_id,
        user_id=current_user.id,
        started_at=now,
        date=now,
        notes=body.notes
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    
    # Reload relation if it was tied to a task
    if task:
        await db.refresh(entry, ["task"])
        # And task.client
        if entry.task:
            await db.refresh(entry.task, ["client"])
            
    return ActiveTimerResponse(
        id=entry.id,
        task_id=entry.task_id,
        task_title=entry.task.title if entry.task else body.notes,
        client_name=entry.task.client.name if entry.task and entry.task.client else None,
        started_at=entry.started_at,
    )


@router.post("/api/timer/stop", response_model=TimeEntryResponse)
async def stop_timer(
    body: TimerStopRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet", write=True)),
):
    result = await db.execute(
        select(TimeEntry).where(
            and_(TimeEntry.user_id == current_user.id, TimeEntry.minutes.is_(None))
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="No hay timer activo")

    now = datetime.utcnow()
    elapsed = (now - entry.started_at).total_seconds()
    entry.minutes = max(1, round(elapsed / 60))
    if body.notes:
        entry.notes = body.notes
    await db.commit()
    await db.refresh(entry)
    return _entry_to_response(entry)


@router.get("/api/timer/active", response_model=Optional[ActiveTimerResponse])
async def get_active_timer(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet")),
):
    result = await db.execute(
        select(TimeEntry).where(
            and_(TimeEntry.user_id == current_user.id, TimeEntry.minutes.is_(None))
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    return ActiveTimerResponse(
        id=entry.id,
        task_id=entry.task_id,
        task_title=entry.task.title if entry.task else entry.notes,
        client_name=entry.task.client.name if entry.task and entry.task.client else None,
        started_at=entry.started_at,
    )

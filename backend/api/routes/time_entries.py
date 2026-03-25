from __future__ import annotations
import logging
from typing import Optional

from datetime import datetime, timezone, timedelta, date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from fastapi.responses import StreamingResponse

from backend.api.utils.db_helpers import safe_refresh
from backend.config import settings
from backend.db.models import TimeEntry, Task, TaskStatus, User, UserRole, Project, Client
from backend.schemas.time_entry import (
    TimeEntryCreate,
    TimeEntryUpdate,
    TimeEntryResponse,
    TimerStartRequest,
    TimerStopRequest,
    ActiveTimerResponse,
    AdminActiveTimerResponse,
    ProjectTimeReport,
    ProjectTeamBreakdown,
    ClientTimeReport,
    ClientTeamBreakdown,
)
from backend.api.deps import get_current_user, require_admin, require_module
from backend.services.csv_utils import build_csv_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["time-entries"])

_TIME_ENTRY_RESPONSE_OPTIONS = (
    selectinload(TimeEntry.task).selectinload(Task.client),
)


async def _sync_task_actual_minutes(db: AsyncSession, task_id: int) -> None:
    """Recompute Task.actual_minutes from the sum of its timer-based time entries.

    Excludes '[manual]' entries (created when user edits actual_minutes directly)
    so they aren't double-counted.  The manual entry represents the portion of
    actual_minutes that didn't come from timers.
    """
    from sqlalchemy import or_

    timer_result = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            TimeEntry.task_id == task_id,
            TimeEntry.minutes.isnot(None),
            or_(TimeEntry.notes != "[manual]", TimeEntry.notes.is_(None)),
        )
    )
    timer_mins = timer_result.scalar() or 0

    manual_result = await db.execute(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(
            TimeEntry.task_id == task_id,
            TimeEntry.notes == "[manual]",
        )
    )
    manual_mins = manual_result.scalar() or 0

    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if task:
        task.actual_minutes = int(timer_mins + manual_mins)


def _entry_to_response(entry: TimeEntry) -> TimeEntryResponse:
    # Safely access relationships — avoid 500 if lazy-load fails in async
    task_title = None
    client_name = None
    try:
        if entry.task:
            task_title = entry.task.title
            if entry.task.client:
                client_name = entry.task.client.name
    except Exception:
        pass  # Relationship not loaded — return None values
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
        task_title=task_title,
        client_name=client_name,
    )


async def _load_time_entry_for_response(db: AsyncSession, entry_id: int) -> TimeEntry | None:
    result = await db.execute(
        select(TimeEntry)
        .options(*_TIME_ENTRY_RESPONSE_OPTIONS)
        .where(TimeEntry.id == entry_id)
    )
    return result.scalar_one_or_none()


# --- CRUD ---

@router.post("/api/time-entries", response_model=TimeEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_time_entry(
    body: TimeEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet", write=True)),
):
    if body.minutes <= 0:
        raise HTTPException(status_code=422, detail="Los minutos deben ser mayores a 0")

    if body.task_id is not None:
        task_result = await db.execute(select(Task).where(Task.id == body.task_id))
        if task_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Task not found")

    entry_date = body.date
    if entry_date and entry_date.tzinfo is not None:
        entry_date = entry_date.astimezone(timezone.utc).replace(tzinfo=None)

    entry = TimeEntry(
        minutes=body.minutes,
        task_id=body.task_id,
        user_id=current_user.id,
        notes=body.notes,
        date=entry_date or datetime.utcnow(),
    )
    db.add(entry)
    await db.commit()

    # Save attributes before they expire (async SQLAlchemy lazy-load guard)
    entry_id = entry.id
    entry_task_id = body.task_id
    entry_user_id = current_user.id
    entry_minutes = body.minutes

    # Automation hook: time_entry_created
    try:
        from backend.api.routes.automations import execute_automations
        await execute_automations("time_entry_created", {
            "time_entry_id": entry_id,
            "task_id": entry_task_id,
            "user_id": entry_user_id,
            "minutes": entry_minutes,
        }, db)
    except Exception as e:
        logger.debug("Automation hook time_entry_created failed (never break time entry creation): %s", e)
        pass  # Never break time entry creation

    if entry_task_id:
        try:
            await _sync_task_actual_minutes(db, entry_task_id)
            await db.commit()
        except Exception:
            logger.warning("Non-critical: task minutes sync failed after time entry creation")
            try:
                await db.rollback()
            except Exception:
                pass
    entry = await _load_time_entry_for_response(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found after create")
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
    query = select(TimeEntry).options(*_TIME_ENTRY_RESPONSE_OPTIONS).where(TimeEntry.minutes.isnot(None))
    # F-05: members can only see their own time entries
    if current_user.role != UserRole.admin:
        query = query.where(TimeEntry.user_id == current_user.id)
    elif user_id is not None:
        query = query.where(TimeEntry.user_id == user_id)
    if task_id is not None:
        query = query.where(TimeEntry.task_id == task_id)
    if date_from is not None:
        query = query.where(TimeEntry.date >= date_from.replace(tzinfo=None))
    if date_to is not None:
        query = query.where(TimeEntry.date <= date_to.replace(tzinfo=None))
    query = query.order_by(TimeEntry.date.desc())
    result = await db.execute(query)
    return [_entry_to_response(e) for e in result.scalars().all()]


@router.get("/api/time-entries/weekly")
async def weekly_timesheet(
    week_start: Optional[date_type] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet")),
):
    today = datetime.utcnow().date()
    if week_start is None:
        week_start = today - timedelta(days=today.weekday())  # Monday
    start_dt = datetime.combine(week_start, datetime.min.time())
    end_dt = start_dt + timedelta(days=7)

    # Load users — non-admin only sees themselves
    if current_user.role == UserRole.admin:
        result = await db.execute(select(User).order_by(User.full_name))
        users = result.scalars().all()
    else:
        users = [current_user]

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

    # Fetch time entries within range — non-admin filtered to own entries
    entry_query = select(TimeEntry).where(
        TimeEntry.minutes.isnot(None),
        TimeEntry.date >= start_dt,
        TimeEntry.date < end_dt,
    )
    if current_user.role != UserRole.admin:
        entry_query = entry_query.where(TimeEntry.user_id == current_user.id)

    result = await db.execute(entry_query)
    entries = result.scalars().all()

    # Batch-load tasks and their clients for task-level breakdown
    task_ids = {e.task_id for e in entries if e.task_id}
    tasks_map: dict[int, dict] = {}
    if task_ids:
        task_result = await db.execute(
            select(Task, Client.name)
            .outerjoin(Client, Task.client_id == Client.id)
            .where(Task.id.in_(task_ids))
        )
        for task, client_name in task_result.all():
            tasks_map[task.id] = {"title": task.title, "client_name": client_name}

    # Initialise per-user task breakdown dict
    for uid in user_map:
        user_map[uid]["tasks"] = {}

    for entry in entries:
        if entry.user_id not in user_map:
            continue
        day_key = entry.date.date().isoformat()
        mins = entry.minutes or 0

        # Accumulate user-level daily totals (existing behaviour)
        if day_key in user_map[entry.user_id]["daily_minutes"]:
            user_map[entry.user_id]["daily_minutes"][day_key] += mins
            user_map[entry.user_id]["total_minutes"] += mins

        # Accumulate task-level breakdown
        tid = entry.task_id or 0  # 0 = unassigned
        tasks = user_map[entry.user_id]["tasks"]
        if tid not in tasks:
            info = tasks_map.get(tid, {"title": "Sin tarea asignada", "client_name": None})
            tasks[tid] = {
                "task_id": tid if tid else None,
                "task_title": info["title"],
                "client_name": info.get("client_name"),
                "daily_minutes": {k: 0 for k in day_keys},
                "total_minutes": 0,
            }
        tasks[tid]["daily_minutes"][day_key] = tasks[tid]["daily_minutes"].get(day_key, 0) + mins
        tasks[tid]["total_minutes"] += mins

    # Convert tasks dict to sorted list
    for uid in user_map:
        user_map[uid]["tasks"] = sorted(
            user_map[uid]["tasks"].values(),
            key=lambda t: -t["total_minutes"],
        )

    return {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "days": day_keys,
        "users": list(user_map.values()),
    }


@router.get("/api/time-entries/export")
async def export_time_entries_csv(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    user_id: Optional[int] = Query(None),
    client_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet")),
):
    query = select(TimeEntry).options(
        selectinload(TimeEntry.user),
        selectinload(TimeEntry.task).selectinload(Task.client),
        selectinload(TimeEntry.task).selectinload(Task.project),
    ).where(TimeEntry.minutes.isnot(None))
    # Members can only export their own entries
    if current_user.role != UserRole.admin:
        query = query.where(TimeEntry.user_id == current_user.id)
    elif user_id is not None:
        query = query.where(TimeEntry.user_id == user_id)
    if date_from is not None:
        query = query.where(TimeEntry.date >= date_from.replace(tzinfo=None))
    if date_to is not None:
        query = query.where(TimeEntry.date <= date_to.replace(tzinfo=None))
    if client_id is not None:
        query = query.join(TimeEntry.task).where(Task.client_id == client_id)
    if project_id is not None:
        if client_id is None:
            query = query.join(TimeEntry.task)
        query = query.where(Task.project_id == project_id)
    query = query.order_by(TimeEntry.date.desc())
    result = await db.execute(query)
    entries = result.scalars().all()

    header = ["Fecha", "Usuario", "Horas", "Minutos", "Tarea", "Proyecto", "Cliente", "Notas"]
    rows = []
    for e in entries:
        task = e.task
        rows.append([
            e.date.strftime("%Y-%m-%d"),
            e.user.full_name if e.user else "",
            round((e.minutes or 0) / 60, 2),
            e.minutes or 0,
            task.title if task else "",
            task.project.name if task and task.project else "",
            task.client.name if task and task.client else "",
            e.notes or "",
        ])
    return build_csv_response("time-entries.csv", header, rows)


@router.get("/api/time-entries/by-project", response_model=list[ProjectTimeReport])
async def time_entries_by_project(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    client_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet")),
):
    query = (
        select(TimeEntry)
        .options(
            selectinload(TimeEntry.task).selectinload(Task.client),
            selectinload(TimeEntry.task).selectinload(Task.project),
            selectinload(TimeEntry.user),
        )
        .where(
            TimeEntry.minutes.isnot(None),
            TimeEntry.task_id.isnot(None),
        )
    )
    # Members can only see their own time entries in aggregates
    if current_user.role != UserRole.admin:
        query = query.where(TimeEntry.user_id == current_user.id)
    if date_from is not None:
        query = query.where(TimeEntry.date >= date_from.replace(tzinfo=None))
    if date_to is not None:
        query = query.where(TimeEntry.date <= date_to.replace(tzinfo=None))
    if client_id is not None:
        query = query.join(TimeEntry.task).where(Task.client_id == client_id)
    result = await db.execute(query)
    entries = result.scalars().all()

    # Group by project, then by user
    project_map: dict[int, dict] = {}
    for e in entries:
        task = e.task
        if not task or not task.project_id:
            continue
        project = task.project
        if not project:
            continue
        pid = project.id
        if pid not in project_map:
            project_map[pid] = {
                "project_id": pid,
                "project_name": project.name,
                "client_id": task.client_id,
                "client_name": task.client.name if task.client else "",
                "total_minutes": 0,
                "entries_count": 0,
                "team": {},
            }
        pm = project_map[pid]
        pm["total_minutes"] += e.minutes or 0
        pm["entries_count"] += 1
        uid = e.user_id
        if uid not in pm["team"]:
            pm["team"][uid] = {
                "user_id": uid,
                "user_name": e.user.full_name if e.user else "",
                "total_minutes": 0,
                "entries_count": 0,
            }
        pm["team"][uid]["total_minutes"] += e.minutes or 0
        pm["team"][uid]["entries_count"] += 1

    reports = []
    for pm in sorted(project_map.values(), key=lambda x: x["total_minutes"], reverse=True):
        reports.append(ProjectTimeReport(
            project_id=pm["project_id"],
            project_name=pm["project_name"],
            client_id=pm["client_id"],
            client_name=pm["client_name"],
            total_minutes=pm["total_minutes"],
            entries_count=pm["entries_count"],
            team_breakdown=[
                ProjectTeamBreakdown(**t) for t in sorted(pm["team"].values(), key=lambda x: x["total_minutes"], reverse=True)
            ],
        ))
    return reports


@router.get("/api/time-entries/by-client", response_model=list[ClientTimeReport])
async def time_entries_by_client(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet")),
):
    query = (
        select(TimeEntry)
        .options(
            selectinload(TimeEntry.task).selectinload(Task.client),
            selectinload(TimeEntry.user),
        )
        .where(
            TimeEntry.minutes.isnot(None),
            TimeEntry.task_id.isnot(None),
        )
    )
    # Members can only see their own time entries in aggregates
    if current_user.role != UserRole.admin:
        query = query.where(TimeEntry.user_id == current_user.id)
    if date_from is not None:
        query = query.where(TimeEntry.date >= date_from.replace(tzinfo=None))
    if date_to is not None:
        query = query.where(TimeEntry.date <= date_to.replace(tzinfo=None))
    result = await db.execute(query)
    entries = result.scalars().all()

    # Group by client
    client_map: dict = {}
    for e in entries:
        task = e.task
        if not task:
            continue
        cid = task.client_id
        cname = task.client.name if task.client else "Sin cliente"
        if cid not in client_map:
            client_map[cid] = {
                "client_id": cid,
                "client_name": cname,
                "total_minutes": 0,
                "entries_count": 0,
                "cost_eur": 0.0,
                "team": {},
            }
        cm = client_map[cid]
        mins = e.minutes or 0
        rate = float((e.user.hourly_rate or settings.DEFAULT_HOURLY_RATE) if e.user else settings.DEFAULT_HOURLY_RATE)
        cost = mins * rate / 60
        cm["total_minutes"] += mins
        cm["entries_count"] += 1
        cm["cost_eur"] += cost
        uid = e.user_id
        if uid not in cm["team"]:
            cm["team"][uid] = {
                "user_id": uid,
                "user_name": e.user.full_name if e.user else "",
                "total_minutes": 0,
                "cost_eur": 0.0,
            }
        cm["team"][uid]["total_minutes"] += mins
        cm["team"][uid]["cost_eur"] += cost

    reports = []
    for cm in sorted(client_map.values(), key=lambda x: x["total_minutes"], reverse=True):
        reports.append(ClientTimeReport(
            client_id=cm["client_id"],
            client_name=cm["client_name"],
            total_minutes=cm["total_minutes"],
            entries_count=cm["entries_count"],
            cost_eur=round(cm["cost_eur"], 2),
            team_breakdown=[
                ClientTeamBreakdown(
                    user_id=t["user_id"],
                    user_name=t["user_name"],
                    total_minutes=t["total_minutes"],
                    cost_eur=round(t["cost_eur"], 2),
                )
                for t in sorted(cm["team"].values(), key=lambda x: x["total_minutes"], reverse=True)
            ],
        ))
    return reports


@router.get("/api/admin/timers/active", response_model=list[AdminActiveTimerResponse])
async def admin_active_timers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(TimeEntry).where(TimeEntry.minutes.is_(None))
    )
    entries = result.scalars().all()
    now = datetime.utcnow()
    return [
        AdminActiveTimerResponse(
            id=e.id,
            user_id=e.user_id,
            user_name=e.user.full_name if e.user else "",
            user_email=e.user.email if e.user else "",
            task_id=e.task_id,
            task_title=e.task.title if e.task else e.notes,
            client_name=e.task.client.name if e.task and e.task.client else None,
            started_at=e.started_at,
            elapsed_seconds=int((now - e.started_at).total_seconds()) if e.started_at else 0,
        )
        for e in entries
    ]


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
    _UPDATABLE_TIME_ENTRY_FIELDS = {"minutes", "notes", "task_id"}
    update_data = body.model_dump(exclude_unset=True)
    old_task_id = entry.task_id
    for field, value in update_data.items():
        if field in _UPDATABLE_TIME_ENTRY_FIELDS:
            setattr(entry, field, value)
    await db.commit()
    # Sync actual_minutes on affected tasks
    affected_tasks = {t for t in [old_task_id, entry.task_id] if t is not None}
    if affected_tasks:
        try:
            for tid in affected_tasks:
                await _sync_task_actual_minutes(db, tid)
            await db.commit()
        except Exception:
            logger.warning("Non-critical: task minutes sync failed after time entry update")
            try:
                await db.rollback()
            except Exception:
                pass
    entry = await _load_time_entry_for_response(db, entry.id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Time entry not found after stop")
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
    task_id = entry.task_id
    await db.delete(entry)
    await db.commit()
    if task_id:
        await _sync_task_actual_minutes(db, task_id)
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
        select(TimeEntry)
        .options(*_TIME_ENTRY_RESPONSE_OPTIONS)
        .where(
            and_(TimeEntry.user_id == current_user.id, TimeEntry.minutes.is_(None))
        )
    )
    active = result.scalar_one_or_none()
    if active is not None:
        # Auto-stop the current timer before starting a new one
        now_stop = datetime.utcnow()
        sa = active.started_at if active.started_at and active.started_at.tzinfo is None else (active.started_at.replace(tzinfo=None) if active.started_at else now_stop)
        elapsed = (now_stop - sa).total_seconds()
        active.minutes = max(1, min(480, round(elapsed / 60)))
        await db.commit()
        if active.task_id:
            try:
                await _sync_task_actual_minutes(db, active.task_id)
                await db.commit()
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass
        
    if body.task_id is None and not body.notes:
        raise HTTPException(status_code=400, detail="Debes enviar un task_id o una nota")

    task = None
    if body.task_id is not None:
        # Verify task exists
        task_result = await db.execute(select(Task).where(Task.id == body.task_id))
        task = task_result.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        # Auto-set task to in_progress when starting timer
        if task.status in (TaskStatus.pending, TaskStatus.backlog):
            task.status = TaskStatus.in_progress

    now = datetime.utcnow()
    entry = TimeEntry(
        task_id=body.task_id,
        user_id=current_user.id,
        started_at=now,
        date=now,
        notes=body.notes
    )
    db.add(entry)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya hay un timer activo. Detén el actual antes de iniciar otro.",
        )
    # Reload with proper eager loading (avoids async lazy-load 500s)
    loaded = await _load_time_entry_for_response(db, entry.id)

    task_title = body.notes
    client_name = None
    if loaded:
        try:
            if loaded.task:
                task_title = loaded.task.title
                if loaded.task.client:
                    client_name = loaded.task.client.name
        except Exception:
            pass
    # If reload failed, task_title stays as body.notes (safe fallback)

    obj = loaded or entry
    sa = obj.started_at
    if sa and sa.tzinfo is None:
        sa = sa.replace(tzinfo=timezone.utc)
    return ActiveTimerResponse(
        id=obj.id,
        task_id=obj.task_id,
        task_title=task_title,
        client_name=client_name,
        started_at=sa,
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
    if not entry.started_at:
        raise HTTPException(status_code=400, detail="Timer has no start time")

    now = datetime.utcnow()
    # Use naive UTC to match DB TIMESTAMP WITHOUT TIME ZONE columns
    sa = entry.started_at if entry.started_at.tzinfo is None else entry.started_at.replace(tzinfo=None)
    elapsed = (now - sa).total_seconds()
    entry.minutes = max(1, min(480, round(elapsed / 60)))  # Cap at 8 hours
    if body.notes:
        entry.notes = body.notes

    await db.commit()
    if entry.task_id:
        try:
            await _sync_task_actual_minutes(db, entry.task_id)
            await db.commit()
        except Exception:
            logger.warning("Non-critical: task minutes sync failed after timer stop")
            try:
                await db.rollback()
            except Exception:
                pass
    # Reload with explicit eager loading instead of safe_refresh
    loaded = await _load_time_entry_for_response(db, entry.id)
    return _entry_to_response(loaded or entry)


@router.get("/api/timer/active", response_model=Optional[ActiveTimerResponse])
async def get_active_timer(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module("timesheet")),
):
    result = await db.execute(
        select(TimeEntry)
        .options(selectinload(TimeEntry.task).selectinload(Task.client))
        .where(
            and_(TimeEntry.user_id == current_user.id, TimeEntry.minutes.is_(None))
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    sa = entry.started_at.replace(tzinfo=timezone.utc) if entry.started_at and entry.started_at.tzinfo is None else entry.started_at
    task_title = entry.notes
    client_name = None
    if entry.task:
        task_title = entry.task.title
        if entry.task.client:
            client_name = entry.task.client.name
    return ActiveTimerResponse(
        id=entry.id,
        task_id=entry.task_id,
        task_title=task_title,
        client_name=client_name,
        started_at=sa,
    )

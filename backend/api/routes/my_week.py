from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_db
from backend.db.models import (
    Task, TaskStatus, TaskComment, Event, EventType,
    User, UserDayStatus, DayStatusType, CompanyHoliday,
)
from backend.api.deps import get_current_user, require_admin
from backend.api.utils.db_helpers import safe_refresh
from backend.schemas.my_week import (
    DayStatusUpdate, DayStatusResponse,
    EventCreate, EventUpdate, EventResponse,
    CompanyHolidayCreate, CompanyHolidayResponse,
    MyWeekTask, MyWeekDay, MyWeekSummary, MyWeekResponse,
)

router = APIRouter(prefix="/api/my-week", tags=["my-week"])

WEEKDAYS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _task_to_response(task: Task, last_comment: Optional[str] = None, last_comment_at: Optional[datetime] = None) -> MyWeekTask:
    checklist = task.checklist_items or []
    weeks_open = 0
    if task.status not in (TaskStatus.completed,) and task.created_at:
        days_open = (datetime.utcnow() - task.created_at).days
        weeks_open = max(0, days_open // 7)

    return MyWeekTask(
        id=task.id,
        title=task.title,
        status=task.status.value if task.status else "pending",
        priority=task.priority.value if task.priority else "medium",
        scheduled_date=task.scheduled_date,
        due_date=task.due_date,
        estimated_minutes=task.estimated_minutes,
        client_id=task.client_id,
        client_name=task.client.name if task.client else None,
        project_id=task.project_id,
        project_name=task.project.name if task.project else None,
        created_at=task.created_at,
        last_comment=last_comment,
        last_comment_at=last_comment_at,
        checklist_total=len(checklist),
        checklist_done=sum(1 for c in checklist if c.is_done),
        weeks_open=weeks_open,
    )


@router.get("", response_model=MyWeekResponse)
async def get_my_week(
    week_start: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get the full My Week view for the current user."""
    if week_start is None:
        week_start = _monday_of(date.today())
    else:
        week_start = _monday_of(week_start)

    week_end = week_start + timedelta(days=6)

    # 1. Fetch active tasks assigned to user
    active_statuses = [TaskStatus.pending, TaskStatus.in_progress, TaskStatus.waiting]
    task_q = (
        select(Task)
        .where(
            Task.assigned_to == user.id,
            Task.status.in_(active_statuses),
        )
        .options(selectinload(Task.client), selectinload(Task.project), selectinload(Task.checklist_items))
        .order_by(Task.scheduled_date.asc().nullslast(), Task.due_date.asc().nullslast(), Task.priority.desc())
    )
    result = await db.execute(task_q)
    all_tasks = result.scalars().all()

    # 2. Batch-fetch last comment per task
    task_ids = [t.id for t in all_tasks]
    last_comments: dict[int, tuple[str, datetime]] = {}
    if task_ids:
        subq = (
            select(TaskComment.task_id, func.max(TaskComment.created_at).label("max_at"))
            .where(TaskComment.task_id.in_(task_ids))
            .group_by(TaskComment.task_id)
            .subquery()
        )
        comment_q = (
            select(TaskComment)
            .join(subq, and_(TaskComment.task_id == subq.c.task_id, TaskComment.created_at == subq.c.max_at))
        )
        comment_result = await db.execute(comment_q)
        for c in comment_result.scalars().all():
            last_comments[c.task_id] = (c.content[:200] if c.content else "", c.created_at)

    # 3. Day statuses
    status_q = select(UserDayStatus).where(
        UserDayStatus.user_id == user.id,
        UserDayStatus.date >= week_start,
        UserDayStatus.date <= week_end,
    )
    status_result = await db.execute(status_q)
    day_statuses = {s.date: s for s in status_result.scalars().all()}

    # 4. Company holidays (filtered by user region)
    from sqlalchemy import or_
    holiday_q = select(CompanyHoliday).where(
        CompanyHoliday.date >= week_start,
        CompanyHoliday.date <= week_end,
    )
    # Only show holidays that apply to this user: national + user's region + user's locality
    region_conditions = [CompanyHoliday.region.is_(None)]  # national always
    if user.region:
        region_conditions.append(
            (CompanyHoliday.region == user.region) & (CompanyHoliday.locality.is_(None))
        )
        if user.locality:
            region_conditions.append(
                (CompanyHoliday.region == user.region) & (CompanyHoliday.locality == user.locality)
            )
    holiday_q = holiday_q.where(or_(*region_conditions))
    holiday_result = await db.execute(holiday_q)
    holidays = {h.date: h for h in holiday_result.scalars().all()}

    # 5. Events
    week_start_dt = datetime(week_start.year, week_start.month, week_start.day)
    week_end_dt = datetime(week_end.year, week_end.month, week_end.day, 23, 59, 59)
    event_q = (
        select(Event)
        .where(
            Event.user_id == user.id,
            Event.start_time >= week_start_dt,
            Event.start_time <= week_end_dt,
        )
        .order_by(Event.start_time.asc())
    )
    event_result = await db.execute(event_q)
    events_list = event_result.scalars().all()

    events_by_date: dict[date, list] = {}
    for ev in events_list:
        d = ev.start_time.date()
        if d not in events_by_date:
            events_by_date[d] = []
        events_by_date[d].append(EventResponse(
            id=ev.id,
            title=ev.title,
            description=ev.description,
            event_type=ev.event_type.value if ev.event_type else "other",
            date=d,
            time=ev.start_time.strftime("%H:%M") if ev.start_time else None,
            start_time=ev.start_time,
            end_time=ev.end_time,
            is_all_day=ev.is_all_day,
            duration_minutes=int((ev.end_time - ev.start_time).total_seconds() / 60) if ev.end_time and ev.start_time else None,
            client_id=ev.client_id,
            client_name=ev.client.name if ev.client else None,
            user_id=ev.user_id,
        ))

    # 6. Categorize tasks
    scheduled_tasks: dict[date, list[Task]] = {}
    backlog_tasks: list[Task] = []

    for t in all_tasks:
        if t.scheduled_date and week_start <= t.scheduled_date <= week_end:
            scheduled_tasks.setdefault(t.scheduled_date, []).append(t)
        elif t.due_date and week_start <= t.due_date.date() <= week_end and not t.scheduled_date:
            d = t.due_date.date()
            scheduled_tasks.setdefault(d, []).append(t)
        else:
            backlog_tasks.append(t)

    # 7. Build days
    days = []
    available_days = 0
    for i in range(7):
        d = week_start + timedelta(days=i)
        weekday = WEEKDAYS_ES[d.weekday()]

        day_status = day_statuses.get(d)
        holiday = holidays.get(d)

        status_resp = DayStatusResponse.model_validate(day_status) if day_status else None
        holiday_resp = CompanyHolidayResponse.model_validate(holiday) if holiday else None

        day_tasks = [
            _task_to_response(t, *last_comments.get(t.id, (None, None)))
            for t in scheduled_tasks.get(d, [])
        ]

        if d.weekday() < 5:
            is_unavailable = (
                holiday is not None
                or (day_status and day_status.status in (DayStatusType.vacation, DayStatusType.sick, DayStatusType.holiday))
            )
            if not is_unavailable:
                available_days += 1

        days.append(MyWeekDay(
            date=d,
            weekday=weekday,
            status=status_resp,
            is_holiday=holiday_resp,
            events=events_by_date.get(d, []),
            tasks=day_tasks,
        ))

    # 8. Backlog
    backlog = [
        _task_to_response(t, *last_comments.get(t.id, (None, None)))
        for t in backlog_tasks
    ]

    # 9. Summary
    all_week_tasks_list: list[Task] = []
    for d_tasks in scheduled_tasks.values():
        all_week_tasks_list.extend(d_tasks)
    all_relevant = all_week_tasks_list + backlog_tasks

    by_client: dict[Optional[int], dict] = {}
    for t in all_relevant:
        cid = t.client_id
        cname = t.client.name if t.client else "Sin cliente"
        if cid not in by_client:
            by_client[cid] = {"client_id": cid, "client_name": cname, "count": 0}
        by_client[cid]["count"] += 1

    daily_hours = (user.weekly_hours or 40) / 5
    summary = MyWeekSummary(
        total_tasks=len(all_relevant),
        estimated_minutes=sum(t.estimated_minutes or 0 for t in all_relevant),
        available_hours=round(available_days * daily_hours, 1),
        tasks_dragging=sum(1 for t in all_relevant if t.created_at and (datetime.utcnow() - t.created_at).days > 7),
        tasks_no_estimate=sum(1 for t in all_relevant if not t.estimated_minutes),
        tasks_no_date=len(backlog_tasks),
        by_client=sorted(by_client.values(), key=lambda x: x["count"], reverse=True),
    )

    return MyWeekResponse(
        week_start=week_start,
        week_end=week_end,
        days=days,
        backlog=backlog,
        summary=summary,
    )


# ── Day Status ──────────────────────────────────────────────

@router.put("/day-status", response_model=DayStatusResponse)
async def upsert_day_status(
    body: DayStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(UserDayStatus).where(
        UserDayStatus.user_id == user.id,
        UserDayStatus.date == body.date,
    )
    result = await db.execute(q)
    existing = result.scalar_one_or_none()

    if existing:
        existing.status = DayStatusType(body.status)
        existing.label = body.label
        existing.note = body.note
    else:
        existing = UserDayStatus(
            user_id=user.id,
            date=body.date,
            status=DayStatusType(body.status),
            label=body.label,
            note=body.note,
        )
        db.add(existing)

    await db.commit()
    await safe_refresh(db, existing, log_context="my_week")
    return existing


@router.delete("/day-status/{status_date}")
async def delete_day_status(
    status_date: date,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(UserDayStatus).where(
        UserDayStatus.user_id == user.id,
        UserDayStatus.date == status_date,
    )
    result = await db.execute(q)
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
    return {"ok": True}


# ── Events ──────────────────────────────────────────────────

@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.time:
        parts = body.time.split(":")
        hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        start_time = datetime(body.date.year, body.date.month, body.date.day, hour, minute)
    else:
        start_time = datetime(body.date.year, body.date.month, body.date.day, 0, 0)

    end_time = None
    if body.duration_minutes:
        end_time = start_time + timedelta(minutes=body.duration_minutes)

    try:
        etype = EventType(body.event_type)
    except ValueError:
        etype = EventType.other

    event = Event(
        title=body.title,
        description=body.description,
        event_type=etype,
        start_time=start_time,
        end_time=end_time,
        is_all_day=body.is_all_day,
        client_id=body.client_id,
        user_id=user.id,
    )
    db.add(event)
    await db.commit()
    await safe_refresh(db, event, log_context="my_week")

    return EventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        date=body.date,
        time=body.time,
        start_time=event.start_time,
        end_time=event.end_time,
        is_all_day=event.is_all_day,
        duration_minutes=body.duration_minutes,
        client_id=event.client_id,
        client_name=event.client.name if event.client else None,
        user_id=event.user_id,
    )


@router.put("/events/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: int,
    body: EventUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Event).where(Event.id == event_id, Event.user_id == user.id)
    result = await db.execute(q)
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if body.title is not None:
        event.title = body.title
    if body.description is not None:
        event.description = body.description
    if body.is_all_day is not None:
        event.is_all_day = body.is_all_day
    if body.client_id is not None:
        event.client_id = body.client_id
    if body.event_type is not None:
        try:
            event.event_type = EventType(body.event_type)
        except ValueError:
            pass

    if body.date is not None or body.time is not None:
        d = body.date or event.start_time.date()
        if body.time is not None:
            parts = body.time.split(":")
            hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        else:
            hour, minute = event.start_time.hour, event.start_time.minute
        event.start_time = datetime(d.year, d.month, d.day, hour, minute)

    if body.duration_minutes is not None:
        event.end_time = event.start_time + timedelta(minutes=body.duration_minutes)

    await db.commit()
    await safe_refresh(db, event, log_context="my_week")

    d = event.start_time.date()
    return EventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        date=d,
        time=event.start_time.strftime("%H:%M"),
        start_time=event.start_time,
        end_time=event.end_time,
        is_all_day=event.is_all_day,
        duration_minutes=int((event.end_time - event.start_time).total_seconds() / 60) if event.end_time else None,
        client_id=event.client_id,
        client_name=event.client.name if event.client else None,
        user_id=event.user_id,
    )


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Event).where(Event.id == event_id, Event.user_id == user.id)
    result = await db.execute(q)
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await db.delete(event)
    await db.commit()
    return {"ok": True}


# ── Task quick-schedule ─────────────────────────────────────

@router.patch("/tasks/{task_id}/schedule")
async def schedule_task(
    task_id: int,
    scheduled_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Task).where(Task.id == task_id)
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assigned_to != user.id and user.role.value != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    task.scheduled_date = scheduled_date
    await db.commit()
    return {"ok": True, "scheduled_date": str(scheduled_date) if scheduled_date else None}


# ── Company Holidays (admin) ────────────────────────────────

@router.get("/holidays", response_model=list[CompanyHolidayResponse])
async def list_holidays(
    year: Optional[int] = Query(None),
    region: Optional[str] = Query(None, description="Filter by CCAA code"),
    include_national: bool = Query(True, description="Include national holidays"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(CompanyHoliday).order_by(CompanyHoliday.date.asc())
    if year:
        q = q.where(
            CompanyHoliday.date >= date(year, 1, 1),
            CompanyHoliday.date <= date(year, 12, 31),
        )
    if region:
        from sqlalchemy import or_
        conditions = [CompanyHoliday.region == region]
        if include_national:
            conditions.append(CompanyHoliday.region.is_(None))
        q = q.where(or_(*conditions))
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/holidays", response_model=CompanyHolidayResponse, status_code=status.HTTP_201_CREATED)
async def create_holiday(
    body: CompanyHolidayCreate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    holiday = CompanyHoliday(
        date=body.date, name=body.name, country=body.country,
        region=body.region, locality=body.locality,
    )
    db.add(holiday)
    await db.commit()
    await safe_refresh(db, holiday, log_context="my_week")
    return holiday


@router.delete("/holidays/{holiday_id}")
async def delete_holiday(
    holiday_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    q = select(CompanyHoliday).where(CompanyHoliday.id == holiday_id)
    result = await db.execute(q)
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    await db.delete(holiday)
    await db.commit()
    return {"ok": True}

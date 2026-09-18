"""Digest Collector: gathers raw data for a client's weekly digest.

Given a client_id and date range, collects:
- Tasks completed in the period
- Tasks in_progress / pending (upcoming)
- Time entries (hours logged)
- Communications with requires_followup
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import (
    IN_PROGRESS_TASK_STATUSES,
    Client,
    CommunicationLog,
    Project,
    Task,
    TaskStatus,
    TimeEntry,
)
from backend.services.temporal import civil_day_utc_bounds
from backend.services.time_entry_dates import time_entry_civil_period

TOP_TASKS_PER_GROUP = 10


def _task_fact(task: Task, project_name: str | None) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description or "",
        "project_id": task.project_id,
        "project_name": project_name,
        "assigned_to": task.assigned_user.full_name if task.assigned_user else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "estimated_minutes": task.estimated_minutes,
        "actual_minutes": task.actual_minutes,
    }


def _new_group(project_id: int | None, project_name: str | None) -> dict:
    return {
        "project_id": project_id,
        "project_name": project_name,
        "progress_percent": None if project_id is None else 0,
        "task_total": 0,
        "completed_total": 0,
        "completed_tasks": [],
        "in_progress_total": 0,
        "in_progress_tasks": [],
        "pending_total": 0,
        "pending_tasks": [],
        "total_minutes": 0,
        "total_hours": 0,
    }


async def collect_digest_data(
    db: AsyncSession,
    client_id: int,
    period_start: date,
    period_end: date,
) -> dict:
    """Collect all relevant data for a client digest within the given period."""

    start_dt, _ = civil_day_utc_bounds(period_start)
    _, end_dt = civil_day_utc_bounds(period_end)

    # --- Client info ---
    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    client_name = client.name if client else "Cliente"

    # Every project is represented independently; client-level tasks live in
    # the explicit unassigned group instead of being attributed to a project.
    project_result = await db.execute(
        select(Project)
        .where(Project.client_id == client_id)
        .order_by(Project.created_at.asc(), Project.id.asc())
    )
    projects = project_result.scalars().all()
    groups = {project.id: _new_group(project.id, project.name) for project in projects}
    groups[None] = _new_group(None, None)
    project_names = {project.id: project.name for project in projects}

    all_tasks_result = await db.execute(
        select(Task)
        .options(selectinload(Task.assigned_user))
        .where(Task.client_id == client_id)
        .order_by(Task.id.asc())
    )
    all_tasks = all_tasks_result.scalars().all()
    completed_all_time = {project_id: 0 for project_id in groups}
    for task in all_tasks:
        group = groups.get(task.project_id, groups[None])
        group["task_total"] += 1
        if task.status == TaskStatus.completed:
            completed_all_time[group["project_id"]] += 1

    for group in groups.values():
        if group["project_id"] is not None and group["task_total"]:
            group["progress_percent"] = int(
                completed_all_time[group["project_id"]] * 100 / group["task_total"]
            )

    # --- Tasks completed in period ---
    completed_result = await db.execute(
        select(Task).options(selectinload(Task.assigned_user)).where(
            Task.client_id == client_id,
            Task.status == TaskStatus.completed,
            Task.completed_at >= start_dt,
            Task.completed_at < end_dt,
        ).order_by(Task.completed_at.desc())
    )
    completed_tasks = []
    for task in completed_result.scalars().all():
        fact = _task_fact(task, project_names.get(task.project_id))
        completed_tasks.append(fact)
        group = groups.get(task.project_id, groups[None])
        group["completed_total"] += 1
        if len(group["completed_tasks"]) < TOP_TASKS_PER_GROUP:
            group["completed_tasks"].append(fact)

    # --- Tasks in progress ---
    in_progress_result = await db.execute(
        select(Task).options(selectinload(Task.assigned_user)).where(
            Task.client_id == client_id,
            Task.status.in_(IN_PROGRESS_TASK_STATUSES),
        ).order_by(Task.due_date.asc().nullslast())
    )
    in_progress_tasks = []
    for task in in_progress_result.scalars().all():
        fact = _task_fact(task, project_names.get(task.project_id))
        in_progress_tasks.append(fact)
        group = groups.get(task.project_id, groups[None])
        group["in_progress_total"] += 1
        if len(group["in_progress_tasks"]) < TOP_TASKS_PER_GROUP:
            group["in_progress_tasks"].append(fact)

    # --- Tasks pending (next up) ---
    pending_result = await db.execute(
        select(Task).options(selectinload(Task.assigned_user)).where(
            Task.client_id == client_id,
            Task.status == TaskStatus.pending,
        ).order_by(Task.due_date.asc().nullslast(), Task.id.asc())
    )
    pending_tasks = []
    for task in pending_result.scalars().all():
        fact = _task_fact(task, project_names.get(task.project_id))
        pending_tasks.append(fact)
        group = groups.get(task.project_id, groups[None])
        group["pending_total"] += 1
        if len(group["pending_tasks"]) < TOP_TASKS_PER_GROUP:
            group["pending_tasks"].append(fact)

    # --- Time entries in period ---
    time_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.minutes.isnot(None),
            time_entry_civil_period(period_start, period_end + timedelta(days=1)),
        ).join(Task, TimeEntry.task_id == Task.id).where(
            Task.client_id == client_id,
        )
    )
    entries = time_result.scalars().all()
    task_projects = {task.id: task.project_id for task in all_tasks}
    total_minutes = 0
    for entry in entries:
        minutes = entry.minutes or 0
        total_minutes += minutes
        project_id = task_projects.get(entry.task_id)
        groups.get(project_id, groups[None])["total_minutes"] += minutes
    total_hours = round(total_minutes / 60, 1)
    for group in groups.values():
        group["total_hours"] = round(group["total_minutes"] / 60, 1)

    # --- Pending followups ---
    followup_result = await db.execute(
        select(CommunicationLog).where(
            CommunicationLog.client_id == client_id,
            CommunicationLog.requires_followup.is_(True),
        ).order_by(CommunicationLog.followup_date.asc())
    )
    followups = [
        {
            "id": f.id,
            "subject": f.subject or "",
            "summary": f.summary,
            "followup_date": f.followup_date.isoformat() if f.followup_date else None,
            "contact_name": f.contact_name,
        }
        for f in followup_result.scalars().all()
    ]

    project_groups = [groups[project.id] for project in projects]
    unassigned = groups[None]
    return {
        "context_version": 2,
        "client_id": client_id,
        "client_name": client_name,
        "projects": project_groups,
        "unassigned": unassigned,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "pending_tasks": pending_tasks,
        "total_hours": total_hours,
        "total_minutes": total_minutes,
        "totals": {
            "project_count": len(project_groups),
            "task_total": sum(group["task_total"] for group in groups.values()),
            "completed_total": len(completed_tasks),
            "in_progress_total": len(in_progress_tasks),
            "pending_total": len(pending_tasks),
            "total_minutes": total_minutes,
            "total_hours": total_hours,
        },
        "pending_followups": followups,
    }

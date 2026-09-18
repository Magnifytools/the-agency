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


def _new_group(
    project_id: int | None,
    project_name: str | None,
    *,
    resolution: str = "resolved",
) -> dict:
    return {
        "project_id": project_id,
        "project_name": project_name,
        "resolution": resolution,
        "progress_percent": 0 if resolution == "resolved" and project_id is not None else None,
        "task_total": 0,
        "completed_total": 0,
        "completed_tasks": [],
        "in_progress_total": 0,
        "in_progress_tasks": [],
        "pending_total": 0,
        "pending_tasks": [],
        "total_minutes": 0,
        "total_hours": 0,
        "historical_template_minutes": 0,
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
    groups[None] = _new_group(None, None, resolution="unassigned")
    unresolved_groups: dict[int, dict] = {}

    def group_for(project_id: int | None) -> dict:
        if project_id in groups:
            return groups[project_id]
        unresolved = unresolved_groups.get(project_id)
        if unresolved is None:
            unresolved = _new_group(
                project_id,
                f"Proyecto no resuelto (ID {project_id})",
                resolution="unresolved",
            )
            unresolved_groups[project_id] = unresolved
        return unresolved

    all_tasks_result = await db.execute(
        select(Task)
        .options(selectinload(Task.assigned_user))
        .where(Task.client_id == client_id, Task.is_recurring.is_(False))
        .order_by(Task.id.asc())
    )
    all_tasks = all_tasks_result.scalars().all()
    completed_all_time: dict[int | None, int] = {}
    for task in all_tasks:
        group = group_for(task.project_id)
        group["task_total"] += 1
        if task.status == TaskStatus.completed:
            completed_all_time[group["project_id"]] = (
                completed_all_time.get(group["project_id"], 0) + 1
            )

    for group in [*groups.values(), *unresolved_groups.values()]:
        if group["resolution"] == "resolved" and group["task_total"]:
            group["progress_percent"] = int(
                completed_all_time.get(group["project_id"], 0)
                * 100
                / group["task_total"]
            )

    # --- Tasks completed in period ---
    completed_result = await db.execute(
        select(Task).options(selectinload(Task.assigned_user)).where(
            Task.client_id == client_id,
            Task.is_recurring.is_(False),
            Task.status == TaskStatus.completed,
            Task.completed_at >= start_dt,
            Task.completed_at < end_dt,
        ).order_by(Task.completed_at.desc())
    )
    completed_tasks = []
    for task in completed_result.scalars().all():
        group = group_for(task.project_id)
        fact = _task_fact(task, group["project_name"])
        completed_tasks.append(fact)
        group["completed_total"] += 1
        if len(group["completed_tasks"]) < TOP_TASKS_PER_GROUP:
            group["completed_tasks"].append(fact)

    # --- Tasks in progress ---
    in_progress_result = await db.execute(
        select(Task).options(selectinload(Task.assigned_user)).where(
            Task.client_id == client_id,
            Task.is_recurring.is_(False),
            Task.status.in_(IN_PROGRESS_TASK_STATUSES),
        ).order_by(Task.due_date.asc().nullslast())
    )
    in_progress_tasks = []
    for task in in_progress_result.scalars().all():
        group = group_for(task.project_id)
        fact = _task_fact(task, group["project_name"])
        in_progress_tasks.append(fact)
        group["in_progress_total"] += 1
        if len(group["in_progress_tasks"]) < TOP_TASKS_PER_GROUP:
            group["in_progress_tasks"].append(fact)

    # --- Tasks pending (next up) ---
    pending_result = await db.execute(
        select(Task).options(selectinload(Task.assigned_user)).where(
            Task.client_id == client_id,
            Task.is_recurring.is_(False),
            Task.status == TaskStatus.pending,
        ).order_by(Task.due_date.asc().nullslast(), Task.id.asc())
    )
    pending_tasks = []
    for task in pending_result.scalars().all():
        group = group_for(task.project_id)
        fact = _task_fact(task, group["project_name"])
        pending_tasks.append(fact)
        group["pending_total"] += 1
        if len(group["pending_tasks"]) < TOP_TASKS_PER_GROUP:
            group["pending_tasks"].append(fact)

    # --- Time entries in period ---
    time_result = await db.execute(
        select(TimeEntry, Task.project_id, Task.is_recurring).where(
            TimeEntry.minutes.isnot(None),
            time_entry_civil_period(period_start, period_end + timedelta(days=1)),
        ).join(Task, TimeEntry.task_id == Task.id).where(
            Task.client_id == client_id,
        )
    )
    entries = time_result.all()
    total_minutes = 0
    historical_template_minutes = 0
    for entry, project_id, is_recurring in entries:
        minutes = entry.minutes or 0
        total_minutes += minutes
        group = group_for(project_id)
        group["total_minutes"] += minutes
        if is_recurring:
            group["historical_template_minutes"] += minutes
            historical_template_minutes += minutes
    total_hours = round(total_minutes / 60, 1)
    for group in [*groups.values(), *unresolved_groups.values()]:
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
    unresolved = list(unresolved_groups.values())
    unassigned = groups[None]
    return {
        "context_version": 2,
        "client_id": client_id,
        "client_name": client_name,
        "projects": project_groups,
        "unresolved_projects": unresolved,
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
            "unresolved_project_count": len(unresolved),
            "task_total": sum(
                group["task_total"]
                for group in [*groups.values(), *unresolved_groups.values()]
            ),
            "completed_total": len(completed_tasks),
            "in_progress_total": len(in_progress_tasks),
            "pending_total": len(pending_tasks),
            "total_minutes": total_minutes,
            "total_hours": total_hours,
            "historical_template_minutes": historical_template_minutes,
        },
        "pending_followups": followups,
    }

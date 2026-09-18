"""Digest Collector: gathers raw data for a client's weekly digest."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    IN_PROGRESS_TASK_STATUSES,
    Client,
    CommunicationLog,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
)
from backend.services.temporal import civil_day_utc_bounds
from backend.services.time_entry_dates import time_entry_civil_period

TOP_TASKS_PER_GROUP = 10
CURRENT_PROJECT_STATUSES = (
    ProjectStatus.planning,
    ProjectStatus.active,
    ProjectStatus.on_hold,
)


def _new_group(
    project_id: int | None, project_name: str | None, *, resolution: str = "resolved"
) -> dict:
    return {
        "project_id": project_id,
        "project_name": project_name,
        "resolution": resolution,
        "progress_percent": 0
        if resolution == "resolved" and project_id is not None
        else None,
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


def _task_fact(row: Any, project_name: str | None) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "project_id": row.project_id,
        "project_name": project_name,
        "assigned_to": row.assigned_to_name,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "estimated_minutes": row.estimated_minutes,
        "actual_minutes": row.actual_minutes,
    }


def _sample_query(*conditions: Any, order_by: tuple[Any, ...]):
    """Return at most TOP_TASKS_PER_GROUP task facts for every project bucket."""
    ranked = (
        select(
            Task.id.label("id"),
            Task.title.label("title"),
            Task.description.label("description"),
            Task.project_id.label("project_id"),
            User.full_name.label("assigned_to_name"),
            Task.due_date.label("due_date"),
            Task.estimated_minutes.label("estimated_minutes"),
            Task.actual_minutes.label("actual_minutes"),
            func.row_number()
            .over(
                partition_by=Task.project_id,
                order_by=order_by,
            )
            .label("rank"),
        )
        .outerjoin(User, User.id == Task.assigned_to)
        .where(Task.is_recurring.is_(False), *conditions)
        .subquery()
    )
    return select(ranked).where(ranked.c.rank <= TOP_TASKS_PER_GROUP)


async def collect_digest_data(
    db: AsyncSession,
    client_id: int,
    period_start: date,
    period_end: date,
) -> dict:
    """Collect bounded, project-grouped facts for a client digest."""
    start_dt, _ = civil_day_utc_bounds(period_start)
    _, end_dt = civil_day_utc_bounds(period_end)

    client_name = (
        await db.scalar(select(Client.name).where(Client.id == client_id)) or "Cliente"
    )

    project_rows = (
        await db.execute(
            select(Project.id, Project.name, Project.status)
            .where(Project.client_id == client_id)
            .order_by(Project.created_at.asc(), Project.id.asc())
        )
    ).all()
    project_catalog = {row.id: row for row in project_rows}
    groups = {
        row.id: _new_group(row.id, row.name)
        for row in project_rows
        if row.status in CURRENT_PROJECT_STATUSES
    }
    groups[None] = _new_group(None, None, resolution="unassigned")
    unresolved_groups: dict[int, dict] = {}

    def group_for(
        project_id: int | None, *, historical_fact: bool = False
    ) -> dict | None:
        if project_id in groups:
            return groups[project_id]
        project = project_catalog.get(project_id)
        if project is not None:
            if not historical_fact:
                return None
            group = _new_group(project.id, project.name)
            groups[project.id] = group
            return group
        group = unresolved_groups.get(project_id)
        if group is None:
            group = _new_group(
                project_id,
                f"Proyecto no resuelto (ID {project_id})",
                resolution="unresolved",
            )
            unresolved_groups[project_id] = group
        return group

    task_totals_rows = (
        await db.execute(
            select(
                Task.project_id,
                func.count(Task.id).label("task_total"),
                func.count(Task.id)
                .filter(Task.status == TaskStatus.completed)
                .label("completed_all_time"),
                func.count(Task.id)
                .filter(
                    Task.status == TaskStatus.completed,
                    Task.completed_at >= start_dt,
                    Task.completed_at < end_dt,
                )
                .label("completed_total"),
                func.count(Task.id)
                .filter(Task.status.in_(IN_PROGRESS_TASK_STATUSES))
                .label("in_progress_total"),
                func.count(Task.id)
                .filter(Task.status == TaskStatus.pending)
                .label("pending_total"),
            )
            .where(Task.client_id == client_id, Task.is_recurring.is_(False))
            .group_by(Task.project_id)
        )
    ).all()
    # Establish the complete included-project cohort before selecting samples.
    # A closed project with period hours remains relevant even when its task was
    # completed outside the period.
    time_rows = (
        await db.execute(
            select(
                Task.project_id,
                Task.is_recurring,
                func.coalesce(func.sum(TimeEntry.minutes), 0).label("minutes"),
            )
            .join(Task, TimeEntry.task_id == Task.id)
            .where(
                Task.client_id == client_id,
                TimeEntry.minutes.isnot(None),
                time_entry_civil_period(period_start, period_end + timedelta(days=1)),
            )
            .group_by(Task.project_id, Task.is_recurring)
        )
    ).all()
    historical_template_minutes = 0
    for row in time_rows:
        group = group_for(row.project_id, historical_fact=True)
        assert group is not None
        minutes = int(row.minutes or 0)
        group["total_minutes"] += minutes
        if row.is_recurring:
            group["historical_template_minutes"] += minutes
            historical_template_minutes += minutes

    for row in task_totals_rows:
        group = group_for(row.project_id, historical_fact=bool(row.completed_total))
        if group is None:
            continue
        group["task_total"] = row.task_total
        group["completed_total"] = row.completed_total
        group["in_progress_total"] = row.in_progress_total
        group["pending_total"] = row.pending_total
        if group["resolution"] == "resolved" and row.task_total:
            group["progress_percent"] = int(
                row.completed_all_time * 100 / row.task_total
            )

    sample_specs = (
        (
            "completed_tasks",
            (
                Task.client_id == client_id,
                Task.status == TaskStatus.completed,
                Task.completed_at >= start_dt,
                Task.completed_at < end_dt,
            ),
            (Task.completed_at.desc(), Task.id.asc()),
            True,
        ),
        (
            "in_progress_tasks",
            (Task.client_id == client_id, Task.status.in_(IN_PROGRESS_TASK_STATUSES)),
            (Task.due_date.asc().nullslast(), Task.id.asc()),
            False,
        ),
        (
            "pending_tasks",
            (Task.client_id == client_id, Task.status == TaskStatus.pending),
            (Task.due_date.asc().nullslast(), Task.id.asc()),
            False,
        ),
    )
    for target, conditions, ordering, historical_fact in sample_specs:
        rows = (await db.execute(_sample_query(*conditions, order_by=ordering))).all()
        for row in rows:
            group = group_for(row.project_id, historical_fact=historical_fact)
            if group is not None:
                group[target].append(_task_fact(row, group["project_name"]))

    all_groups = [*groups.values(), *unresolved_groups.values()]
    for group in all_groups:
        group["total_hours"] = round(group["total_minutes"] / 60, 1)

    followup_rows = (
        await db.execute(
            select(
                CommunicationLog.id,
                CommunicationLog.subject,
                CommunicationLog.summary,
                CommunicationLog.followup_date,
                CommunicationLog.contact_name,
            )
            .where(
                CommunicationLog.client_id == client_id,
                CommunicationLog.requires_followup.is_(True),
            )
            .order_by(CommunicationLog.followup_date.asc())
        )
    ).all()
    followups = [
        {
            "id": row.id,
            "subject": row.subject or "",
            "summary": row.summary,
            "followup_date": row.followup_date.isoformat()
            if row.followup_date
            else None,
            "contact_name": row.contact_name,
        }
        for row in followup_rows
    ]

    included_projects = [groups[row.id] for row in project_rows if row.id in groups]
    unresolved = list(unresolved_groups.values())
    unassigned = groups[None]
    total_minutes = sum(group["total_minutes"] for group in all_groups)
    total_hours = round(total_minutes / 60, 1)
    return {
        "context_version": 2,
        "client_id": client_id,
        "client_name": client_name,
        "projects": included_projects,
        "unresolved_projects": unresolved,
        "unassigned": unassigned,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_hours": total_hours,
        "total_minutes": total_minutes,
        "totals": {
            "project_count": len(included_projects),
            "unresolved_project_count": len(unresolved),
            "task_total": sum(group["task_total"] for group in all_groups),
            "completed_total": sum(group["completed_total"] for group in all_groups),
            "in_progress_total": sum(
                group["in_progress_total"] for group in all_groups
            ),
            "pending_total": sum(group["pending_total"] for group in all_groups),
            "total_minutes": total_minutes,
            "total_hours": total_hours,
            "historical_template_minutes": historical_template_minutes,
        },
        "pending_followups": followups,
    }

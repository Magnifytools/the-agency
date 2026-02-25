"""Digest Collector: gathers raw data for a client's weekly digest.

Given a client_id and date range, collects:
- Tasks completed in the period
- Tasks in_progress / pending (upcoming)
- Time entries (hours logged)
- Communications with requires_followup
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Task, TaskStatus, TimeEntry, CommunicationLog, Client, Project,
)


async def collect_digest_data(
    db: AsyncSession,
    client_id: int,
    period_start: date,
    period_end: date,
) -> dict:
    """Collect all relevant data for a client digest within the given period."""

    start_dt = datetime.combine(period_start, datetime.min.time())
    end_dt = datetime.combine(period_end, datetime.max.time())

    # --- Client info ---
    client_result = await db.execute(select(Client).where(Client.id == client_id))
    client = client_result.scalar_one_or_none()
    client_name = client.name if client else "Cliente"

    # --- Project info (1 client = 1 project assumption) ---
    project_result = await db.execute(
        select(Project).where(Project.client_id == client_id).order_by(Project.created_at.desc()).limit(1)
    )
    project = project_result.scalar_one_or_none()

    # --- Tasks completed in period ---
    completed_result = await db.execute(
        select(Task).where(
            Task.client_id == client_id,
            Task.status == TaskStatus.completed,
            Task.updated_at >= start_dt,
            Task.updated_at <= end_dt,
        ).order_by(Task.updated_at.desc())
    )
    completed_tasks = [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description or "",
            "assigned_to": t.assigned_user.full_name if t.assigned_user else None,
            "estimated_minutes": t.estimated_minutes,
            "actual_minutes": t.actual_minutes,
        }
        for t in completed_result.scalars().all()
    ]

    # --- Tasks in progress ---
    in_progress_result = await db.execute(
        select(Task).where(
            Task.client_id == client_id,
            Task.status == TaskStatus.in_progress,
        ).order_by(Task.due_date.asc().nullslast())
    )
    in_progress_tasks = [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description or "",
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "assigned_to": t.assigned_user.full_name if t.assigned_user else None,
        }
        for t in in_progress_result.scalars().all()
    ]

    # --- Tasks pending (next up) ---
    pending_result = await db.execute(
        select(Task).where(
            Task.client_id == client_id,
            Task.status == TaskStatus.pending,
        ).order_by(Task.due_date.asc().nullslast()).limit(10)
    )
    pending_tasks = [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description or "",
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "assigned_to": t.assigned_user.full_name if t.assigned_user else None,
        }
        for t in pending_result.scalars().all()
    ]

    # --- Time entries in period ---
    time_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.minutes.isnot(None),
            TimeEntry.date >= start_dt,
            TimeEntry.date <= end_dt,
        ).join(Task, TimeEntry.task_id == Task.id).where(
            Task.client_id == client_id,
        )
    )
    entries = time_result.scalars().all()
    total_minutes = sum(e.minutes or 0 for e in entries)
    total_hours = round(total_minutes / 60, 1)

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

    return {
        "client_id": client_id,
        "client_name": client_name,
        "project_name": project.name if project else None,
        "project_progress": project.progress_percent if project else None,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "pending_tasks": pending_tasks,
        "total_hours": total_hours,
        "total_minutes": total_minutes,
        "pending_followups": followups,
    }

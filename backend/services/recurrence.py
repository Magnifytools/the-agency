"""Pure recurrence planning plus the idempotent daily materializer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.services.temporal import business_today

RecurrenceState = Literal[
    "inactive", "active", "paused", "ended", "blocked_client", "blocked_project", "invalid"
]


@dataclass(frozen=True)
class RecurrenceSummary:
    state: RecurrenceState
    reason: str | None
    label: str
    next_dates: list[date]


def validate_recurrence_rule(
    *, is_recurring: bool, pattern: str | None, day: int | None,
    anchor_date: date | None, end_date: date | None,
) -> None:
    if not is_recurring:
        return
    if pattern not in {"daily", "weekly", "biweekly", "monthly"}:
        raise ValueError("Selecciona una frecuencia válida")
    if pattern in {"weekly", "biweekly"} and (day is None or not 0 <= day <= 4):
        raise ValueError("El día semanal debe estar entre lunes y viernes")
    if pattern == "monthly" and (day is None or not 1 <= day <= 28):
        raise ValueError("El día mensual debe estar entre 1 y 28")
    if anchor_date is not None and end_date is not None and end_date < anchor_date:
        raise ValueError("La fecha de fin no puede ser anterior al inicio de la recurrencia")


def is_due_on(
    candidate: date, *, pattern: str, day: int | None,
    anchor_date: date | None = None, end_date: date | None = None,
) -> bool:
    if end_date is not None and candidate > end_date:
        return False
    if anchor_date is not None and candidate < anchor_date:
        return False
    if pattern == "daily":
        return candidate.weekday() < 5
    if pattern == "weekly":
        return candidate.weekday() == day
    if pattern == "monthly":
        return candidate.day == day
    if pattern == "biweekly":
        if candidate.weekday() != day:
            return False
        if anchor_date is None:
            # Historical contract: ISO even weeks, including year boundaries.
            return candidate.isocalendar().week % 2 == 0
        try:
            first = anchor_date + timedelta(days=((day or 0) - anchor_date.weekday()) % 7)
        except OverflowError:
            return False
        return candidate >= first and (candidate - first).days % 14 == 0
    return False


def _label(pattern: str | None, day: int | None, anchor_date: date | None) -> str:
    weekday = ("lunes", "martes", "miércoles", "jueves", "viernes")
    if pattern == "daily":
        return "Cada día laborable (lunes a viernes)"
    if pattern == "weekly" and day is not None and 0 <= day <= 4:
        return f"Cada {weekday[day]}"
    if pattern == "biweekly" and day is not None and 0 <= day <= 4:
        suffix = f" a partir de {anchor_date.isoformat()}" if anchor_date else " (semanas ISO pares)"
        return f"Cada dos semanas, el {weekday[day]}{suffix}"
    if pattern == "monthly" and day is not None:
        return f"El día {day} de cada mes"
    return "Sin recurrencia"


def summarize_recurrence(
    *, is_recurring: bool, pattern: str | None, day: int | None,
    anchor_date: date | None, end_date: date | None, paused: bool,
    client_active: bool = True, project_active: bool = True,
    as_of: date | None = None, count: int = 3,
) -> RecurrenceSummary:
    label = _label(pattern, day, anchor_date)
    if not is_recurring:
        return RecurrenceSummary("inactive", "La tarea no es recurrente", label, [])
    try:
        validate_recurrence_rule(
            is_recurring=True, pattern=pattern, day=day,
            anchor_date=anchor_date, end_date=end_date,
        )
    except ValueError as exc:
        return RecurrenceSummary("invalid", str(exc), label, [])
    today = as_of or business_today()
    if end_date is not None and end_date < today:
        return RecurrenceSummary("ended", "La recurrencia ya ha finalizado", label, [])
    if paused:
        return RecurrenceSummary("paused", "La recurrencia está pausada", label, [])
    if not client_active:
        return RecurrenceSummary("blocked_client", "El cliente está inactivo", label, [])
    if not project_active:
        return RecurrenceSummary("blocked_project", "El proyecto está inactivo", label, [])
    dates: list[date] = []
    candidate = max(today, anchor_date) if anchor_date is not None else today
    if end_date is not None:
        limit = end_date
    else:
        try:
            limit = candidate + timedelta(days=366 * 2)
        except OverflowError:
            limit = date.max
    while candidate <= limit and len(dates) < count:
        if is_due_on(candidate, pattern=pattern or "", day=day,
                     anchor_date=anchor_date, end_date=end_date):
            dates.append(candidate)
        if candidate == date.max:
            break
        candidate += timedelta(days=1)
    return RecurrenceSummary("active", None, label, dates)


async def generate_recurring_instances(db: AsyncSession, *, target_date: date | None = None) -> int:
    """Materialize due templates for one business date; caller owns the session."""
    from backend.db.models import (
        Client, ClientStatus, Project, ProjectStatus, Task,
        TaskRecurrenceOccurrence, TaskStatus,
    )
    from backend.services.change_journal import paused as journal_paused
    from backend.services.domain_writes import create_task

    today = target_date or business_today()
    # Shared first lock with destructive Client/Project writers. It prevents
    # scope deletion from crossing template discovery and materialization.
    await db.execute(text("SELECT pg_advisory_xact_lock(76241317)"))
    templates = list((await db.execute(
        select(Task).where(
            Task.is_recurring.is_(True),
            Task.recurrence_paused_at.is_(None),
            or_(Task.client_id.is_(None), Task.client.has(Client.status == ClientStatus.active)),
            or_(Task.project_id.is_(None), Task.project.has(Project.status == ProjectStatus.active)),
            or_(Task.recurrence_end_date.is_(None), Task.recurrence_end_date >= today),
        ).options(noload("*")).order_by(Task.id).with_for_update()
        .execution_options(populate_existing=True)
    )).scalars())
    created = 0
    with journal_paused():
        for template in templates:
            try:
                validate_recurrence_rule(
                    is_recurring=True, pattern=template.recurrence_pattern,
                    day=template.recurrence_day,
                    anchor_date=template.recurrence_anchor_date,
                    end_date=template.recurrence_end_date,
                )
            except ValueError as exc:
                import logging
                logging.warning("Recurring task %s has an invalid rule: %s", template.id, exc)
                continue
            if not is_due_on(
                today, pattern=template.recurrence_pattern or "", day=template.recurrence_day,
                anchor_date=template.recurrence_anchor_date,
                end_date=template.recurrence_end_date,
            ):
                continue
            consumed = (await db.execute(select(TaskRecurrenceOccurrence.id).where(
                TaskRecurrenceOccurrence.template_id == template.id,
                TaskRecurrenceOccurrence.date == today,
            ).limit(1))).scalar_one_or_none()
            if consumed is not None:
                continue
            existing = (await db.execute(select(Task.id).where(
                Task.recurring_parent_id == template.id,
                or_(
                    Task.recurrence_occurrence_date == today,
                    (Task.recurrence_occurrence_date.is_(None)) & (Task.scheduled_date == today),
                ),
            ).order_by(Task.id).limit(1).with_for_update())).scalar_one_or_none()
            if existing is not None:
                # Observing a legacy child for today consumes today's slot
                # prospectively, without inventing an occurrence date on it.
                db.add(TaskRecurrenceOccurrence(
                    template_id=template.id, date=today, task_id=existing,
                ))
                await db.flush()
                continue
            data = {
                "title": template.title, "description": template.description,
                "client_id": template.client_id, "project_id": template.project_id,
                "phase_id": template.phase_id, "estimated_minutes": template.estimated_minutes,
                "category_id": template.category_id, "assigned_to": template.assigned_to,
                "priority": template.priority, "status": TaskStatus.pending,
                "scheduled_date": today, "due_date": datetime.combine(today, time.min),
                "recurring_parent_id": template.id, "is_recurring": False,
                "recurrence_occurrence_date": today,
            }
            try:
                async with db.begin_nested():
                    task = await create_task(
                        db, data, actor=None, created_by=template.created_by,
                    )
                    db.add(TaskRecurrenceOccurrence(
                        template_id=template.id, date=today, task_id=task.id,
                    ))
                    await db.flush()
                created += 1
            except IntegrityError as exc:
                # The partial unique index makes concurrent workers converge here.
                if any(name in str(exc) for name in (
                    "uq_task_recurring_occurrence", "uq_task_recurrence_consumed",
                )):
                    continue
                raise
            except HTTPException as exc:
                import logging
                logging.warning("Recurring task %s skipped: %s", template.id, exc.detail)
    await db.commit()
    return created

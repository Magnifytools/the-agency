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


PATTERNS = frozenset({
    "daily", "weekly", "weekdays", "biweekly", "monthly", "quarterly", "last_business_day",
})
# Una fecha que cae en sábado, domingo o festivo se trabaja el siguiente día
# hábil. Ningún tramo de días no hábiles se acerca a este tope.
MAX_SHIFT_DAYS = 14
# Si el job no corrió algún día, recupera lo que faltó de esta última semana.
CATCH_UP_DAYS = 7
WEEKDAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes")


def is_business_day(day: date, holidays: frozenset[date] = frozenset()) -> bool:
    return day.weekday() < 5 and day not in holidays


def validate_recurrence_rule(
    *, is_recurring: bool, pattern: str | None, day: int | None,
    anchor_date: date | None, end_date: date | None, weekdays: list[int] | None = None,
) -> None:
    if not is_recurring:
        return
    if pattern not in PATTERNS:
        raise ValueError("Selecciona una frecuencia válida")
    if pattern in {"weekly", "biweekly"} and (day is None or not 0 <= day <= 4):
        raise ValueError("El día semanal debe estar entre lunes y viernes")
    if pattern in {"monthly", "quarterly"} and (day is None or not 1 <= day <= 28):
        raise ValueError("El día del mes debe estar entre 1 y 28")
    if pattern == "weekdays" and (
        not weekdays or len(set(weekdays)) != len(weekdays)
        or any(not isinstance(value, int) or not 0 <= value <= 4 for value in weekdays)
    ):
        raise ValueError("Elige al menos un día, de lunes a viernes")
    if anchor_date is not None and end_date is not None and end_date < anchor_date:
        raise ValueError("La fecha de fin no puede ser anterior al inicio de la recurrencia")


def _last_business_day(year: int, month: int, holidays: frozenset[date]) -> date:
    day = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)) - timedelta(days=1)
    while not is_business_day(day, holidays):
        day -= timedelta(days=1)
    return day


def is_due_on(
    candidate: date, *, pattern: str, day: int | None,
    anchor_date: date | None = None, end_date: date | None = None,
    weekdays: list[int] | None = None, holidays: frozenset[date] = frozenset(),
) -> bool:
    """¿Es ``candidate`` una fecha de la regla? Fecha nominal: el día en que se
    trabaja puede ser otro (ver ``work_date``)."""
    if end_date is not None and candidate > end_date:
        return False
    if anchor_date is not None and candidate < anchor_date:
        return False
    if pattern == "daily":
        return candidate.weekday() < 5
    if pattern == "weekly":
        return candidate.weekday() == day
    if pattern == "weekdays":
        return candidate.weekday() in (weekdays or ())
    if pattern == "monthly":
        return candidate.day == day
    if pattern == "quarterly":
        first_month = anchor_date.month if anchor_date is not None else 1
        return candidate.day == day and (candidate.month - first_month) % 3 == 0
    if pattern == "last_business_day":
        return candidate == _last_business_day(candidate.year, candidate.month, holidays)
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


def work_date(nominal: date, *, pattern: str, holidays: frozenset[date] = frozenset()) -> date | None:
    """Día en que se crea la tarea de una fecha nominal: el mismo si es hábil;
    si no, el siguiente hábil. La diaria se salta los festivos (si no, el día
    siguiente tendría dos)."""
    if pattern == "daily":
        return nominal if is_business_day(nominal, holidays) else None
    day = nominal
    try:
        while not is_business_day(day, holidays):
            day += timedelta(days=1)
    except OverflowError:
        return None
    return day


def nominal_dates_for(
    work_day: date, *, pattern: str, day: int | None, anchor_date: date | None,
    end_date: date | None, weekdays: list[int] | None = None,
    holidays: frozenset[date] = frozenset(),
) -> list[date]:
    """Fechas nominales que se trabajan ``work_day``. Casi siempre una; dos si
    un festivo empuja una sobre la siguiente (lunes festivo con lunes y martes):
    entonces es UNA tarea."""
    if not is_business_day(work_day, holidays):
        return []
    found = []
    for offset in range(MAX_SHIFT_DAYS, -1, -1):
        try:
            nominal = work_day - timedelta(days=offset)
        except OverflowError:
            continue
        if is_due_on(
            nominal, pattern=pattern, day=day, anchor_date=anchor_date,
            end_date=end_date, weekdays=weekdays, holidays=holidays,
        ) and work_date(nominal, pattern=pattern, holidays=holidays) == work_day:
            found.append(nominal)
    return found


def _label(pattern: str | None, day: int | None, anchor_date: date | None, weekdays: list[int] | None = None) -> str:
    if pattern == "daily":
        return "Cada día laborable (lunes a viernes)"
    if pattern == "weekly" and day is not None and 0 <= day <= 4:
        return f"Cada {WEEKDAY_NAMES[day]}"
    if pattern == "weekdays" and weekdays and all(0 <= value <= 4 for value in weekdays):
        names = [WEEKDAY_NAMES[value] for value in sorted(weekdays)]
        return "Cada " + (", ".join(names[:-1]) + " y " + names[-1] if len(names) > 1 else names[0])
    if pattern == "biweekly" and day is not None and 0 <= day <= 4:
        suffix = f" a partir de {anchor_date.isoformat()}" if anchor_date else " (semanas ISO pares)"
        return f"Cada dos semanas, el {WEEKDAY_NAMES[day]}{suffix}"
    if pattern == "monthly" and day is not None:
        return f"El día {day} de cada mes"
    if pattern == "quarterly" and day is not None:
        first_month = anchor_date.month if anchor_date is not None else 1
        months = sorted((first_month - 1 + 3 * step) % 12 + 1 for step in range(4))
        names = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
        return f"Cada tres meses, el día {day} ({', '.join(names[m - 1] for m in months)})"
    if pattern == "last_business_day":
        return "El último día hábil de cada mes"
    return "Sin recurrencia"


def summarize_recurrence(
    *, is_recurring: bool, pattern: str | None, day: int | None,
    anchor_date: date | None, end_date: date | None, paused: bool,
    client_active: bool = True, project_active: bool = True,
    as_of: date | None = None, count: int = 3,
    weekdays: list[int] | None = None, holidays: frozenset[date] = frozenset(),
) -> RecurrenceSummary:
    """``next_dates`` son días de TRABAJO: ya movidos por fines de semana y por
    los festivos que se pasen (los de quien lleva la plantilla)."""
    label = _label(pattern, day, anchor_date, weekdays)
    if not is_recurring:
        return RecurrenceSummary("inactive", "La tarea no es recurrente", label, [])
    try:
        validate_recurrence_rule(
            is_recurring=True, pattern=pattern, day=day,
            anchor_date=anchor_date, end_date=end_date, weekdays=weekdays,
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
    start = max(today, anchor_date) if anchor_date is not None else today
    try:
        candidate = start - timedelta(days=MAX_SHIFT_DAYS)
    except OverflowError:
        candidate = date.min
    if end_date is not None:
        limit = end_date
    else:
        try:
            limit = start + timedelta(days=366 * 2)
        except OverflowError:
            limit = date.max
    while candidate <= limit and len(dates) < count:
        if is_due_on(candidate, pattern=pattern or "", day=day, anchor_date=anchor_date,
                     end_date=end_date, weekdays=weekdays, holidays=holidays):
            worked = work_date(candidate, pattern=pattern or "", holidays=holidays)
            if worked is not None and worked >= start and worked not in dates:
                dates.append(worked)
        if candidate == date.max:
            break
        candidate += timedelta(days=1)
    return RecurrenceSummary("active", None, label, dates)


def _copy_checklist(db: AsyncSession, task_id: int, items) -> None:
    """Every occurrence starts with a fresh, unticked copy of the template's
    checklist. Dates are not copied: they belong to one specific occurrence."""
    from backend.db.models import TaskChecklist

    for item in items:
        db.add(TaskChecklist(
            task_id=task_id, text=item.text, description=item.description,
            order_index=item.order_index, assigned_to=item.assigned_to, is_done=False,
        ))


async def generate_recurring_instances(db: AsyncSession, *, target_date: date | None = None) -> int:
    """Materialize due templates up to one business date; caller owns the session.

    Crea lo que toca ``today`` y, si el job no corrió algún día, lo que faltó de
    los últimos ``CATCH_UP_DAYS`` (nunca antes de ``recurrence_since``: una pausa
    o un cambio de regla no rellena el pasado). El día de trabajo se mueve por
    fines de semana y por los festivos de quien lleva la plantilla.
    """
    from backend.db.models import (
        Client, ClientStatus, Project, ProjectStatus, Task, TaskChecklist,
        TaskRecurrenceOccurrence, TaskStatus, User,
    )
    from backend.services.change_journal import paused as journal_paused
    from backend.services.domain_writes import create_task
    from backend.services.holidays import load_calendar

    today = target_date or business_today()
    oldest = today - timedelta(days=CATCH_UP_DAYS)
    # Shared first lock with destructive Client/Project writers. It prevents
    # scope deletion from crossing template discovery and materialization.
    await db.execute(text("SELECT pg_advisory_xact_lock(76241317)"))
    templates = list((await db.execute(
        select(Task).where(
            Task.retired_at.is_(None),
            Task.is_recurring.is_(True),
            Task.recurrence_paused_at.is_(None),
            or_(Task.client_id.is_(None), Task.client.has(Client.status == ClientStatus.active)),
            or_(Task.project_id.is_(None), Task.project.has(Project.status == ProjectStatus.active)),
            or_(
                Task.recurrence_end_date.is_(None),
                Task.recurrence_end_date >= oldest - timedelta(days=MAX_SHIFT_DAYS),
            ),
        ).options(noload("*")).order_by(Task.id).with_for_update()
        .execution_options(populate_existing=True)
    )).scalars())
    checklist_by_template: dict[int, list[TaskChecklist]] = {}
    assignees: dict[int, User] = {}
    if templates:
        for item in (await db.execute(
            select(TaskChecklist).where(TaskChecklist.task_id.in_([t.id for t in templates]))
            .options(noload("*")).order_by(TaskChecklist.order_index, TaskChecklist.id)
        )).scalars():
            checklist_by_template.setdefault(item.task_id, []).append(item)
        user_ids = {t.assigned_to for t in templates if t.assigned_to is not None}
        if user_ids:
            assignees = {user.id: user for user in (await db.execute(
                select(User).where(User.id.in_(user_ids)).options(noload("*"))
            )).scalars()}
    # Cubre el último día hábil del mes anterior y los desplazamientos.
    calendar = await load_calendar(db, oldest - timedelta(days=62), today + timedelta(days=31))
    created = 0
    with journal_paused():
        for template in templates:
            rule = {
                "pattern": template.recurrence_pattern or "",
                "day": template.recurrence_day,
                "anchor_date": template.recurrence_anchor_date,
                "end_date": template.recurrence_end_date,
                "weekdays": template.recurrence_weekdays,
            }
            try:
                validate_recurrence_rule(is_recurring=True, **rule)
            except ValueError as exc:
                import logging
                logging.warning("Recurring task %s has an invalid rule: %s", template.id, exc)
                continue
            holidays = calendar.for_user(assignees.get(template.assigned_to))
            since = template.recurrence_since
            first_day = min(today, max(oldest, since)) if since is not None else today
            work_day = first_day
            while work_day <= today:
                current, work_day = work_day, work_day + timedelta(days=1)
                # Lo de hoy se crea siempre (como antes); lo recuperado, sólo
                # si su fecha es posterior al suelo.
                nominals = [
                    nominal for nominal in nominal_dates_for(current, holidays=holidays, **rule)
                    if current == today or nominal >= since
                ]
                if not nominals:
                    continue
                consumed = set((await db.execute(select(TaskRecurrenceOccurrence.date).where(
                    TaskRecurrenceOccurrence.template_id == template.id,
                    TaskRecurrenceOccurrence.date.in_(nominals),
                ))).scalars())
                pending = [nominal for nominal in nominals if nominal not in consumed]
                if not pending:
                    continue
                existing = (await db.execute(select(Task.id).where(
                    Task.recurring_parent_id == template.id,
                    or_(
                        Task.recurrence_occurrence_date.in_(pending),
                        (Task.recurrence_occurrence_date.is_(None)) & (Task.scheduled_date == current),
                    ),
                ).order_by(Task.id).limit(1).with_for_update())).scalar_one_or_none()
                if existing is not None:
                    # Observing a legacy child for this day consumes its slot
                    # prospectively, without inventing an occurrence date on it.
                    for nominal in pending:
                        db.add(TaskRecurrenceOccurrence(
                            template_id=template.id, date=nominal, task_id=existing,
                        ))
                    await db.flush()
                    continue
                data = {
                    "title": template.title, "description": template.description,
                    "client_id": template.client_id, "project_id": template.project_id,
                    "phase_id": template.phase_id, "estimated_minutes": template.estimated_minutes,
                    "category_id": template.category_id, "assigned_to": template.assigned_to,
                    "priority": template.priority, "status": TaskStatus.pending,
                    "scheduled_date": current, "due_date": datetime.combine(current, time.min),
                    "recurring_parent_id": template.id, "is_recurring": False,
                    "recurrence_occurrence_date": pending[0],
                    "procedure_text": template.procedure_text,
                    "procedure_url": template.procedure_url,
                }
                try:
                    async with db.begin_nested():
                        task = await create_task(
                            db, data, actor=None, created_by=template.created_by,
                        )
                        for nominal in pending:
                            db.add(TaskRecurrenceOccurrence(
                                template_id=template.id, date=nominal, task_id=task.id,
                            ))
                        _copy_checklist(db, task.id, checklist_by_template.get(template.id, ()))
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
                    break
    await db.commit()
    return created

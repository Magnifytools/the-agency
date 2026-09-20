"""Operational project conditions derived from explicit commitments and real time."""
from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta
from types import SimpleNamespace

from sqlalchemy import Date, and_, case, cast, false, func, literal, or_, select

from backend.core.modules import is_enabled
from backend.db.models import (
    Notification,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    TimeEntry,
)
from backend.services.incident_conditions import Condition, module_permission
from backend.services.temporal import business_today
from backend.services.time_budget import CLOSING_SOON_DAYS, effective_budgets
from backend.services.time_entry_dates import time_entry_civil_period

PROJECT_NO_NEXT_ACTION = "project_no_next_action"
PROJECT_CLOSING_SOON = "project_closing_soon"
PROJECT_CLOSING_OVERDUE = "project_closing_overdue"
PROJECT_MONTHLY_HOURS_WARNING = "project_monthly_hours_warning"
PROJECT_MONTHLY_HOURS_EXCEEDED = "project_monthly_hours_exceeded"
PROJECT_HOURS_WARNING = "project_hours_warning"
PROJECT_HOURS_EXCEEDED = "project_hours_exceeded"

PROJECT_CONDITIONS = (
    PROJECT_NO_NEXT_ACTION,
    PROJECT_CLOSING_SOON,
    PROJECT_CLOSING_OVERDUE,
    PROJECT_MONTHLY_HOURS_WARNING,
    PROJECT_MONTHLY_HOURS_EXCEEDED,
    PROJECT_HOURS_WARNING,
    PROJECT_HOURS_EXCEEDED,
)

_ELIGIBLE_STATUSES = (ProjectStatus.active, ProjectStatus.planning)
_NEXT_ACTION_STATUSES = tuple(
    status for status in TaskStatus
    if status not in (TaskStatus.completed, TaskStatus.waiting, TaskStatus.backlog)
)


def _key(kind: str, project_id: int, cycle: str) -> str:
    return f"{kind}:project:{project_id}:{cycle}"


def _condition(
    kind: str,
    project_id: int,
    cycle: str,
    title: str,
    message: str,
    *,
    severity: str = "warning",
    legacy_since: datetime | None = None,
) -> Condition:
    key = _key(kind, project_id, cycle)
    return Condition(
        key=key,
        kind=kind,
        entity_id=project_id,
        title=title[:255],
        message=message,
        fingerprint=hashlib.sha256(key.encode()).hexdigest(),
        severity=severity,
        entity_type="project",
        entity_key=str(project_id),
        href=f"/projects/{project_id}",
        legacy_since=legacy_since,
    )


def _hours(value: float) -> str:
    return f"{value:.1f}h".replace(".0h", "h")


def _project_rows(now: datetime):
    today = business_today(now=now)
    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    next_actions = (
        select(Task.project_id.label("project_id"))
        .where(
            Task.project_id.is_not(None),
            Task.retired_at.is_(None),
            Task.is_recurring.is_(False),
            Task.status.in_(_NEXT_ACTION_STATUSES),
            or_(Task.scheduled_date.is_not(None), Task.due_date.is_not(None)),
        )
        .group_by(Task.project_id)
        .subquery()
    )
    monthly_minutes = (
        select(
            Task.project_id.label("project_id"),
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("minutes"),
        )
        .join(TimeEntry, TimeEntry.task_id == Task.id)
        .where(
            Task.project_id.is_not(None),
            TimeEntry.minutes.is_not(None),
            time_entry_civil_period(month_start, next_month),
        )
        .group_by(Task.project_id)
        .subquery()
    )
    total_minutes = (
        select(
            Task.project_id.label("project_id"),
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("minutes"),
        )
        .join(TimeEntry, TimeEntry.task_id == Task.id)
        .where(Task.project_id.is_not(None), TimeEntry.minutes.is_not(None))
        .group_by(Task.project_id)
        .subquery()
    )
    return select(
        Project.id,
        Project.name,
        Project.status,
        Project.start_date,
        Project.target_end_date,
        Project.is_recurring,
        Project.pricing_model,
        Project.budget_hours,
        Project.weekly_hours_budget,
        Project.monthly_hours_budget,
        next_actions.c.project_id.is_not(None).label("has_next_action"),
        func.coalesce(monthly_minutes.c.minutes, 0).label("month_minutes"),
        func.coalesce(total_minutes.c.minutes, 0).label("total_minutes"),
        module_permission(Project.owner_id, "tasks").label("tasks_read"),
        module_permission(Project.owner_id, "timesheet").label("timesheet_read"),
    ).outerjoin(
        next_actions, next_actions.c.project_id == Project.id,
    ).outerjoin(
        monthly_minutes, monthly_minutes.c.project_id == Project.id,
    ).outerjoin(
        total_minutes, total_minutes.c.project_id == Project.id,
    ).where(
        Project.owner_id.is_not(None),
        Project.status.in_(_ELIGIBLE_STATUSES),
        module_permission(Project.owner_id, "projects"),
    ).order_by(Project.id)


async def collect_project_conditions(db, user_id: int, now: datetime) -> dict[str, Condition]:
    """Collect project conditions for one explicit owner in one bounded SELECT."""
    if not is_enabled("projects"):
        return {}
    today = business_today(now=now)
    month_cycle = today.strftime("%Y-%m")
    month_start = datetime.combine(today.replace(day=1), time.min)
    rows = (await db.execute(_project_rows(now).where(Project.owner_id == user_id))).all()
    result: dict[str, Condition] = {}

    for row in rows:
        href_name = row.name or f"Proyecto #{row.id}"
        end_date = row.target_end_date.date() if row.target_end_date else None

        if (
            row.status == ProjectStatus.active
            and is_enabled("tasks")
            and row.tasks_read
            and not row.has_next_action
        ):
            condition = _condition(
                PROJECT_NO_NEXT_ACTION,
                row.id,
                "open",
                f"Proyecto sin próxima acción: {href_name}",
                "No hay ninguna tarea concreta planificada con fecha. Añade o programa el siguiente paso.",
            )
            result[condition.key] = condition

        if end_date is not None:
            days_left = (end_date - today).days
            if days_left < 0:
                condition = _condition(
                    PROJECT_CLOSING_OVERDUE,
                    row.id,
                    end_date.isoformat(),
                    f"Cierre vencido: {href_name}",
                    f"El compromiso de cierre venció el {end_date:%d/%m/%Y}, hace {abs(days_left)} días.",
                    severity="critical",
                    legacy_since=datetime.combine(end_date, time.min),
                )
                result[condition.key] = condition
            elif days_left <= CLOSING_SOON_DAYS:
                when = "hoy" if days_left == 0 else f"en {days_left} días"
                condition = _condition(
                    PROJECT_CLOSING_SOON,
                    row.id,
                    end_date.isoformat(),
                    f"Cierre próximo: {href_name}",
                    f"El compromiso de cierre es {when}, el {end_date:%d/%m/%Y}.",
                    legacy_since=datetime.combine(end_date - timedelta(days=CLOSING_SOON_DAYS), time.min),
                )
                result[condition.key] = condition

        if not row.timesheet_read or not is_enabled("timesheet"):
            continue
        project_view = SimpleNamespace(
            monthly_hours_budget=row.monthly_hours_budget,
            weekly_hours_budget=row.weekly_hours_budget,
            is_recurring=row.is_recurring,
            pricing_model=row.pricing_model,
            budget_hours=row.budget_hours,
        )
        _, monthly_budget = effective_budgets(project_view)
        if monthly_budget and monthly_budget > 0:
            used = float(row.month_minutes or 0) / 60
            ratio = used / float(monthly_budget)
            if ratio >= 1:
                kind, severity = PROJECT_MONTHLY_HOURS_EXCEEDED, "critical"
            elif ratio >= 0.8:
                kind, severity = PROJECT_MONTHLY_HOURS_WARNING, "warning"
            else:
                kind = None
            if kind:
                condition = _condition(
                    kind,
                    row.id,
                    month_cycle,
                    f"Horas del mes en {href_name}: {int(ratio * 100)}%",
                    f"Tiempo registrado: {_hours(used)}. Presupuesto mensual: {_hours(float(monthly_budget))}.",
                    severity=severity,
                    legacy_since=month_start,
                )
                result[condition.key] = condition

        is_monthly = bool(row.is_recurring) or row.pricing_model == "monthly"
        if not is_monthly and row.budget_hours and row.budget_hours > 0:
            used = float(row.total_minutes or 0) / 60
            ratio = used / float(row.budget_hours)
            if ratio >= 1:
                kind, severity = PROJECT_HOURS_EXCEEDED, "critical"
            elif ratio >= 0.8:
                kind, severity = PROJECT_HOURS_WARNING, "warning"
            else:
                kind = None
            if kind:
                cycle = end_date.isoformat() if end_date else "open"
                condition = _condition(
                    kind,
                    row.id,
                    cycle,
                    f"Presupuesto de horas en {href_name}: {int(ratio * 100)}%",
                    f"Tiempo registrado: {_hours(used)}. Presupuesto total: {_hours(float(row.budget_hours))}.",
                    severity=severity,
                )
                result[condition.key] = condition
    return result


def _monthly_budget_expr():
    return case(
        (Project.monthly_hours_budget > 0, Project.monthly_hours_budget),
        (
            and_(
                Project.budget_hours > 0,
                or_(Project.is_recurring.is_(True), Project.pricing_model == "monthly"),
            ),
            Project.budget_hours,
        ),
        else_=None,
    )


def project_visibility_clause(user_id: int, *, current_only: bool = False, now: datetime | None = None):
    """SQL visibility for project incidents, including live-source checks."""
    if not is_enabled("projects"):
        return false()
    permission = and_(
        module_permission(user_id, "projects"),
        or_(
            and_(
                Notification.type == PROJECT_NO_NEXT_ACTION,
                is_enabled("tasks"),
                module_permission(user_id, "tasks"),
            ),
            and_(
                Notification.type.in_((
                    PROJECT_MONTHLY_HOURS_WARNING,
                    PROJECT_MONTHLY_HOURS_EXCEEDED,
                    PROJECT_HOURS_WARNING,
                    PROJECT_HOURS_EXCEEDED,
                )),
                is_enabled("timesheet"),
                module_permission(user_id, "timesheet"),
            ),
            Notification.type.in_((PROJECT_CLOSING_SOON, PROJECT_CLOSING_OVERDUE)),
        ),
    )
    base = and_(
        Notification.user_id == user_id,
        Notification.entity_type == "project",
        Notification.type.in_(PROJECT_CONDITIONS),
        permission,
        select(literal(1)).where(
            Project.id == Notification.entity_id,
            Project.owner_id == user_id,
        ).exists(),
    )
    if not current_only:
        return base

    today = business_today(now=now)
    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    has_next = select(literal(1)).where(
        Task.project_id == Project.id,
        Task.retired_at.is_(None),
        Task.is_recurring.is_(False),
        Task.status.in_(_NEXT_ACTION_STATUSES),
        or_(Task.scheduled_date.is_not(None), Task.due_date.is_not(None)),
    ).exists()
    month_minutes = select(func.coalesce(func.sum(TimeEntry.minutes), 0)).select_from(Task).join(
        TimeEntry, TimeEntry.task_id == Task.id,
    ).where(
        Task.project_id == Project.id,
        TimeEntry.minutes.is_not(None),
        time_entry_civil_period(month_start, next_month),
    ).scalar_subquery()
    total_minutes = select(func.coalesce(func.sum(TimeEntry.minutes), 0)).select_from(Task).join(
        TimeEntry, TimeEntry.task_id == Task.id,
    ).where(Task.project_id == Project.id, TimeEntry.minutes.is_not(None)).scalar_subquery()
    end_date = cast(Project.target_end_date, Date)
    monthly_budget = _monthly_budget_expr()
    fixed_budget = and_(
        Project.budget_hours > 0,
        Project.is_recurring.is_(False),
        or_(Project.pricing_model.is_(None), Project.pricing_model != "monthly"),
    )
    month_cycle = today.strftime("%Y-%m")
    fixed_cycle = case(
        (Project.target_end_date.is_not(None), func.to_char(Project.target_end_date, "YYYY-MM-DD")),
        else_="open",
    )
    cycle_key = lambda kind, cycle: func.concat(kind, ":project:", Project.id, ":", cycle)
    live = select(literal(1)).where(
        Project.id == Notification.entity_id,
        Project.owner_id == user_id,
        Project.status.in_(_ELIGIBLE_STATUSES),
        or_(
            and_(
                Notification.type == PROJECT_NO_NEXT_ACTION,
                Project.status == ProjectStatus.active,
                ~has_next,
                Notification.dedupe_key == cycle_key(PROJECT_NO_NEXT_ACTION, "open"),
            ),
            and_(
                Notification.type == PROJECT_CLOSING_SOON,
                end_date >= today,
                end_date <= today + timedelta(days=CLOSING_SOON_DAYS),
                Notification.dedupe_key == cycle_key(PROJECT_CLOSING_SOON, func.to_char(Project.target_end_date, "YYYY-MM-DD")),
            ),
            and_(
                Notification.type == PROJECT_CLOSING_OVERDUE,
                end_date < today,
                Notification.dedupe_key == cycle_key(PROJECT_CLOSING_OVERDUE, func.to_char(Project.target_end_date, "YYYY-MM-DD")),
            ),
            and_(
                Notification.type == PROJECT_MONTHLY_HOURS_WARNING,
                monthly_budget > 0,
                month_minutes >= monthly_budget * 60 * 0.8,
                month_minutes < monthly_budget * 60,
                Notification.dedupe_key == cycle_key(PROJECT_MONTHLY_HOURS_WARNING, month_cycle),
            ),
            and_(
                Notification.type == PROJECT_MONTHLY_HOURS_EXCEEDED,
                monthly_budget > 0,
                month_minutes >= monthly_budget * 60,
                Notification.dedupe_key == cycle_key(PROJECT_MONTHLY_HOURS_EXCEEDED, month_cycle),
            ),
            and_(
                Notification.type == PROJECT_HOURS_WARNING,
                fixed_budget,
                total_minutes >= Project.budget_hours * 60 * 0.8,
                total_minutes < Project.budget_hours * 60,
                Notification.dedupe_key == cycle_key(PROJECT_HOURS_WARNING, fixed_cycle),
            ),
            and_(
                Notification.type == PROJECT_HOURS_EXCEEDED,
                fixed_budget,
                total_minutes >= Project.budget_hours * 60,
                Notification.dedupe_key == cycle_key(PROJECT_HOURS_EXCEEDED, fixed_cycle),
            ),
        ),
    ).exists()
    return and_(base, live)

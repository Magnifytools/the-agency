"""Horas que pasan de un mes al siguiente (opción por proyecto ``hours_carryover``).

Regla (sencilla a propósito, para que cualquiera la pueda rehacer a mano):

- Sólo proyectos con techo mensual de horas (``effective_budgets``) y la opción
  encendida.
- El saldo del mes anterior = techo mensual − horas registradas ese mes. Si
  sobran, se suman a este mes; si se pasó, el exceso se resta.
- Sólo un mes y sin cadena: el saldo del mes anterior se mide contra su techo
  base, no contra lo que a su vez arrastraba. Así unas horas sin gastar no se
  acumulan sin fin y un mes desbordado no persigue al proyecto para siempre.
- El techo de este mes nunca baja de 0 (el exceso se come como mucho un mes).
- Se mide con el techo ACTUAL (no hay histórico de techos), igual que el ciclo
  mensual ("Diferencia con presupuesto actual").
- Un proyecto que empezó este mes no arrastra nada (su mes anterior no existía):
  manda ``start_date`` y, sin ella, ``created_at``.

Lo leen las mismas piezas que el techo sin arrastre: avisos del proyecto
(``incident_project_conditions``), fila "Operación" del dashboard, ficha del
proyecto, ciclo mensual y la extensión (``/api/timer/project-budget``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, case, func, or_, select

from backend.db.models import Project, Task, TimeEntry
from backend.services.temporal import civil_day_utc_bounds
from backend.services.time_entry_dates import time_entry_civil_period


@dataclass(frozen=True)
class MonthBudget:
    base: float | None      # techo mensual sin arrastre
    budget: float | None    # techo de este mes (con arrastre si aplica)
    carried: float | None   # horas que pasan del mes anterior (+ sobran / − exceso); None si no aplica


def previous_month_start(month_start: date) -> date:
    return (month_start - timedelta(days=1)).replace(day=1)


def started_before(start_date: datetime | None, created_at: datetime | None, month_start: date) -> bool:
    """¿Existía el proyecto el mes anterior? ``start_date`` es civil; ``created_at``, UTC ingenuo."""
    if start_date is not None:
        return start_date < datetime.combine(month_start, time.min)
    if created_at is not None:
        utc_start, _ = civil_day_utc_bounds(month_start)
        return created_at < utc_start
    return False


def month_budget(
    base: float | None,
    *,
    carryover: bool,
    previous_minutes: float | None,
    eligible: bool,
) -> MonthBudget:
    if not base or base <= 0:
        return MonthBudget(base=None, budget=None, carried=None)
    base = float(base)
    if not carryover or not eligible or previous_minutes is None:
        return MonthBudget(base=base, budget=base, carried=None)
    # Sin redondear: el aviso compara con esto; se redondea al enseñarlo.
    carried = base - float(previous_minutes) / 60
    return MonthBudget(base=base, budget=max(0.0, base + carried), carried=carried)


# ── SQL (avisos y fila "Operación": una sola consulta para todos los proyectos) ──

def previous_month_minutes_subquery(month_start: date):
    """Minutos registrados por proyecto el mes anterior a ``month_start``."""
    prev_start = previous_month_start(month_start)
    return (
        select(
            Task.project_id.label("project_id"),
            func.coalesce(func.sum(TimeEntry.minutes), 0).label("minutes"),
        )
        .join(TimeEntry, TimeEntry.task_id == Task.id)
        .where(
            Task.project_id.is_not(None),
            TimeEntry.minutes.is_not(None),
            time_entry_civil_period(prev_start, month_start),
        )
        .group_by(Task.project_id)
        .subquery()
    )


def eligible_clause(month_start: date):
    utc_start, _ = civil_day_utc_bounds(month_start)
    return or_(
        and_(Project.start_date.is_not(None), Project.start_date < datetime.combine(month_start, time.min)),
        and_(Project.start_date.is_(None), Project.created_at < utc_start),
    )


def budget_minutes_expr(base_hours, previous_minutes, month_start: date):
    """Techo de este mes en MINUTOS (SQL), gemelo de ``month_budget``.

    ``base_hours`` es la expresión del techo base. Ojo: ``GREATEST`` ignora los
    NULL, así que sin techo devuelve 0; quien lo use exige antes ``base > 0``.
    """
    base_minutes = base_hours * 60
    carried = case(
        (and_(Project.hours_carryover.is_(True), eligible_clause(month_start)),
         base_minutes - func.coalesce(previous_minutes, 0)),
        else_=0,
    )
    return func.greatest(base_minutes + carried, 0)


# ── Un proyecto (ficha, ciclo mensual, extensión) ─────────────────────────────

async def project_month_budget(db, project, base: float | None, month_start: date) -> MonthBudget:
    """Techo del mes que empieza en ``month_start`` para un proyecto concreto.

    ``project`` necesita ``id``, ``hours_carryover``, ``start_date`` y ``created_at``.
    Sólo consulta la base si el arrastre aplica.
    """
    eligible = started_before(getattr(project, "start_date", None), getattr(project, "created_at", None), month_start)
    if not base or base <= 0 or not getattr(project, "hours_carryover", False) or not eligible:
        return month_budget(base, carryover=False, previous_minutes=None, eligible=False)
    previous = await db.scalar(
        select(func.coalesce(func.sum(TimeEntry.minutes), 0))
        .join(Task, Task.id == TimeEntry.task_id)
        .where(
            Task.project_id == project.id,
            TimeEntry.minutes.is_not(None),
            time_entry_civil_period(previous_month_start(month_start), month_start),
        )
    )
    return month_budget(base, carryover=True, previous_minutes=float(previous or 0), eligible=True)

"""Time-budget status helper.

Computes per-project time-budget status for a given window (week / month)
from already-aggregated minutes. Pure functions — no DB access — so the same
thresholds are reused by the project detail endpoint and the timer/extension
endpoint without drift.

Design (acordado con David, jun 2026):
- El presupuesto SEMANAL (`weekly_hours_budget`) es guía visual / informativa.
- El techo MENSUAL (`monthly_hours_budget`) es el que dispara la notificación dura
  (warning 80%, alerta 100%) — ver `api/routes/notifications.py`.
"""
from __future__ import annotations

WARNING_THRESHOLD = 0.8
OVER_THRESHOLD = 1.0


def _status(pct: float | None) -> str | None:
    """Map a usage ratio to a status string, or None when there's no budget."""
    if pct is None:
        return None
    if pct >= OVER_THRESHOLD:
        return "over"
    if pct >= WARNING_THRESHOLD:
        return "warning"
    return "ok"


def _window(budget_hours: float | None, used_minutes: float) -> dict:
    """Build the status block for a single window (week or month)."""
    used_hours = round(used_minutes / 60, 2)
    if budget_hours and budget_hours > 0:
        budget_minutes = budget_hours * 60
        pct = used_minutes / budget_minutes
        remaining_hours = round((budget_minutes - used_minutes) / 60, 2)
        return {
            "budget_hours": round(float(budget_hours), 2),
            "used_hours": used_hours,
            "remaining_hours": remaining_hours,
            "pct": round(pct, 3),
            "status": _status(pct),
        }
    return {
        "budget_hours": None,
        "used_hours": used_hours,
        "remaining_hours": None,
        "pct": None,
        "status": None,
    }


def effective_budgets(project) -> tuple[float | None, float | None]:
    """Resolve the (weekly, monthly) hours budget a project should be measured against.

    Projects rarely fill the dedicated `monthly_hours_budget` ("techo de alerta").
    What they DO fill, on retainers, is `budget_hours` — the pricing form labels it
    literally "Presupuesto horas/mes" for monthly projects. So a recurring / monthly
    project's `budget_hours` IS its monthly hours allocation, and we fall back to it
    instead of forcing double data entry (CLAUDE.md: No Datos Decorativos).

    For non-recurring projects `budget_hours` is a life-of-project total, NOT monthly,
    so we never derive a monthly ceiling from it there.

    The weekly figure is purely a visual guide, so when it's missing we derive it from
    the monthly ceiling (≈4.33 weeks/month).
    """
    monthly = project.monthly_hours_budget
    weekly = project.weekly_hours_budget

    is_monthly = bool(getattr(project, "is_recurring", False)) or \
        getattr(project, "pricing_model", None) == "monthly"
    budget_hours = getattr(project, "budget_hours", None)
    if (monthly is None or monthly <= 0) and is_monthly and budget_hours and budget_hours > 0:
        monthly = float(budget_hours)

    if (weekly is None or weekly <= 0) and monthly and monthly > 0:
        weekly = round(monthly / 4.33, 1)

    return weekly, monthly


CLOSING_SOON_DAYS = 7
# Pace risk: hours consumed running ahead of schedule by this much (fraction of total)
PACE_RISK_MARGIN = 0.15


def is_recurring_project(project) -> bool:
    """True for retainers / monthly projects (monthly hours ceiling applies)."""
    return bool(getattr(project, "is_recurring", False)) or \
        getattr(project, "pricing_model", None) == "monthly"


def build_closing_status(project, used_minutes_total: float, today) -> dict | None:
    """Closing status for a *puntual* (non-recurring) project with an end date.

    Combines two signals (acordado con David, jun 2026):
    - Proximidad del cierre: avisa a ≤7 días de `target_end_date`, alerta si vencido.
    - Horas vs tiempo restante: para un proyecto cerrado, `budget_hours` es el techo
      total; si el ritmo de horas va por delante del plazo, se queda sin horas antes
      de cerrar.

    Returns None when the project has no end date (nothing to close against).
    """
    end_dt = getattr(project, "target_end_date", None)
    if end_dt is None:
        return None
    end_date = end_dt.date() if hasattr(end_dt, "date") else end_dt
    days_left = (end_date - today).days
    overdue = days_left < 0

    used_hours = round(used_minutes_total / 60, 2)
    budget_hours = getattr(project, "budget_hours", None)
    hours_pct: float | None = None
    remaining_hours: float | None = None
    if budget_hours and budget_hours > 0:
        hours_pct = round(used_minutes_total / (budget_hours * 60), 3)
        remaining_hours = round((budget_hours * 60 - used_minutes_total) / 60, 2)

    # Fraction of the timeline already elapsed (needs a start date).
    start_dt = getattr(project, "start_date", None)
    time_pct: float | None = None
    if start_dt is not None:
        start_date = start_dt.date() if hasattr(start_dt, "date") else start_dt
        total_days = (end_date - start_date).days
        if total_days > 0:
            elapsed = (today - start_date).days
            time_pct = round(min(1.0, max(0.0, elapsed / total_days)), 3)

    # Pace risk: hours run ahead of the schedule and we're past halfway on hours.
    pace_risk = (
        hours_pct is not None
        and time_pct is not None
        and hours_pct >= 0.5
        and hours_pct > time_pct + PACE_RISK_MARGIN
    )

    over_hours = hours_pct is not None and hours_pct >= 1.0
    if overdue or over_hours:
        status = "over"
    elif (0 <= days_left <= CLOSING_SOON_DAYS) or pace_risk:
        status = "warning"
    else:
        status = "ok"

    return {
        "target_end_date": end_date.isoformat(),
        "days_left": days_left,
        "overdue": overdue,
        "budget_hours": round(float(budget_hours), 2) if budget_hours else None,
        "used_hours": used_hours,
        "remaining_hours": remaining_hours,
        "hours_pct": hours_pct,
        "time_pct": time_pct,
        "pace_risk": pace_risk,
        "status": status,
    }


def build_budget_status(
    weekly_budget: float | None,
    monthly_budget: float | None,
    week_minutes: float,
    month_minutes: float,
) -> dict:
    """Return a serializable budget-status dict for week + month windows."""
    return {
        "week": _window(weekly_budget, week_minutes),
        "month": _window(monthly_budget, month_minutes),
    }

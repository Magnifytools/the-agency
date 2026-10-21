"""Canonical civil-period contract for weekly client digests."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Date, case, cast, extract, func, literal_column

from backend.services.temporal import business_today

_MONTHS = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def last_closed_weekly_period(*, today: date | None = None) -> tuple[date, date]:
    """Return the Monday-Sunday week immediately before the business week."""
    civil_today = today or business_today()
    current_monday = civil_today - timedelta(days=civil_today.weekday())
    return current_monday - timedelta(days=7), current_monday - timedelta(days=1)


def last_closed_monthly_period(*, today: date | None = None) -> tuple[date, date]:
    """Return the previous closed natural month in the business timezone."""
    civil_today = today or business_today()
    current_month = civil_today.replace(day=1)
    period_end = current_month - timedelta(days=1)
    return period_end.replace(day=1), period_end


def policy_digest_period(cadence: str, *, today: date | None = None) -> tuple[date, date]:
    if cadence == "weekly":
        return last_closed_weekly_period(today=today)
    if cadence == "monthly":
        return last_closed_monthly_period(today=today)
    raise ValueError("Cadencia de resumen no válida")


CADENCES = ("monthly", "weekly")


def enabled_cadences(policy) -> list[str]:
    """Cadencias encendidas de una política (mensual primero); vacía sin política."""
    if policy is None:
        return []
    return [c for c, on in (("monthly", policy.monthly_enabled), ("weekly", policy.weekly_enabled)) if on]


def period_cadence(period_start: date, period_end: date) -> str | None:
    """La cadencia sale del periodo: semana lunes-domingo o mes natural completo."""
    if period_start.weekday() == 0 and period_end == period_start + timedelta(days=6):
        return "weekly"
    if period_start.day == 1 and period_end == (period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1):
        return "monthly"
    return None


def period_cadence_sql(start_col, end_col):
    """Gemelo SQL de ``period_cadence``: NULL si el periodo no es de ninguna cadencia."""
    month_end = cast(func.date_trunc("month", start_col) + literal_column("interval '1 month - 1 day'"), Date)
    return case(
        (
            (extract("isodow", start_col) == 1) & (end_col == start_col + literal_column("6")),
            "weekly",
        ),
        (
            (extract("day", start_col) == 1) & (end_col == month_end),
            "monthly",
        ),
        else_=None,
    )


def resolve_digest_period(
    period_start: date | None,
    period_end: date | None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """Resolve an explicit complete range or the last closed business week."""
    if (period_start is None) != (period_end is None):
        raise ValueError("Debes indicar period_start y period_end juntos")
    if period_start is None:
        return last_closed_weekly_period(today=today)
    if period_end < period_start:
        raise ValueError("period_end no puede ser anterior a period_start")
    return period_start, period_end


def format_digest_period(period_start: date, period_end: date) -> str:
    """Return the canonical persisted and rendered Spanish period label."""
    if period_start.year == period_end.year and period_start.month == period_end.month:
        return (
            f"Período del {period_start.day} al {period_end.day} "
            f"de {_MONTHS[period_end.month]} de {period_end.year}"
        )
    return (
        f"Período del {period_start.day} de {_MONTHS[period_start.month]} "
        f"de {period_start.year} al {period_end.day} de {_MONTHS[period_end.month]} "
        f"de {period_end.year}"
    )


def format_month(day: date) -> str:
    """'septiembre de 2026'."""
    return f"{_MONTHS[day.month]} de {day.year}"


def canonicalize_digest_content(
    content: dict,
    period_start: date,
    period_end: date,
) -> dict:
    """Copy generated/edited content with its authoritative civil-period label."""
    return {**content, "date": format_digest_period(period_start, period_end)}

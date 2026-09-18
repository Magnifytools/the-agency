"""Canonical civil-period contract for weekly client digests."""

from __future__ import annotations

from datetime import date, timedelta

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


def canonicalize_digest_content(
    content: dict,
    period_start: date,
    period_end: date,
) -> dict:
    """Copy generated/edited content with its authoritative civil-period label."""
    return {**content, "date": format_digest_period(period_start, period_end)}

"""Periodos del informe SEO local y fechas en español.

Mes natural → se compara con el mes natural anterior y con el mismo mes del
año anterior. Parte de un mes desde el día 1 (un mes en curso, como el 1-26 de
octubre de 2026) → con los mismos días del mes anterior y del año anterior.
Cualquier otro rango → con los mismos días justo antes y con el mismo rango
del año anterior.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")
SERIES_MONTHS = 15


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day: date, months: int) -> date:
    """Mismo día `months` meses después (o antes), recortado al último del mes."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last))


def year_before(day: date) -> date:
    return add_months(day, -12)


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def long_date(day: date) -> str:
    """'28 de octubre de 2026'."""
    return f"{day.day} de {MONTHS[day.month - 1]} de {day.year}"


def range_label(start: date, end: date) -> str:
    """'1 al 26 de octubre de 2026', 'octubre de 2026', '29 de septiembre al 5 de octubre de 2026'."""
    if start.day == 1 and end == month_end(start) and start.month == end.month and start.year == end.year:
        return f"{MONTHS[start.month - 1]} de {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"{start.day} al {end.day} de {MONTHS[end.month - 1]} de {end.year}"
    if start.year == end.year:
        return f"{start.day} de {MONTHS[start.month - 1]} al {end.day} de {MONTHS[end.month - 1]} de {end.year}"
    return f"{long_date(start)} al {long_date(end)}"


def short_date(day: date) -> str:
    """'29 jun 2025'."""
    return f"{day.day} {MONTHS[day.month - 1][:3]} {day.year}"


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    @property
    def label(self) -> str:
        return range_label(self.start, self.end)

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label}


@dataclass(frozen=True)
class ReportPeriods:
    current: Window
    previous: Window
    year_ago: Window
    # Los tres meses que acaban en el periodo y los mismos del año anterior.
    quarter: Window
    quarter_year_ago: Window
    # Serie mensual: sólo meses completos (15, hasta el último completo).
    series: Window
    series_months: tuple[str, ...]
    kind: str  # month | partial_month | range

    @property
    def mes_datos(self) -> str:
        return month_key(self.current.start)

    @property
    def full_month(self) -> bool:
        return self.kind == "month"


def compute(start: date, end: date) -> ReportPeriods:
    if start > end:
        raise ValueError("El inicio del periodo no puede ser posterior al final")
    same_month = (start.year, start.month) == (end.year, end.month)
    if start.day == 1 and same_month and end == month_end(start):
        kind = "month"
        prev_start = add_months(start, -1)
        previous = Window(prev_start, month_end(prev_start))
        yoy_start = year_before(start)
        year_ago = Window(yoy_start, month_end(yoy_start))
    elif start.day == 1 and same_month:
        kind = "partial_month"
        prev_start = add_months(start, -1)
        previous = Window(prev_start, min(add_months(end, -1), month_end(prev_start)))
        year_ago = Window(year_before(start), year_before(end))
    else:
        kind = "range"
        days = (end - start).days + 1
        previous = Window(start - timedelta(days=days), start - timedelta(days=1))
        year_ago = Window(year_before(start), year_before(end))

    quarter_start = add_months(end.replace(day=1), -2)
    quarter = Window(quarter_start, end)
    quarter_year_ago = Window(year_before(quarter_start), year_before(end))

    last_full = end.replace(day=1) if end == month_end(end) else add_months(end.replace(day=1), -1)
    first = add_months(last_full, -(SERIES_MONTHS - 1))
    months = tuple(month_key(add_months(first, i)) for i in range(SERIES_MONTHS))
    series = Window(first, month_end(last_full))
    return ReportPeriods(Window(start, end), previous, year_ago, quarter, quarter_year_ago,
                         series, months, kind)


def default_period(today: date) -> tuple[date, date]:
    """El mes natural anterior a hoy (se genera el día 5)."""
    first = add_months(today.replace(day=1), -1)
    return first, month_end(first)

"""Unit tests for the time-budget helper, focused on the effective-budget
fallback: recurring/monthly retainers use `budget_hours` ("Presupuesto horas/mes")
as their monthly ceiling when no explicit `monthly_hours_budget` is set.
"""
from __future__ import annotations

from types import SimpleNamespace

from datetime import date, datetime, timedelta

from backend.services.time_budget import (
    effective_budgets,
    build_budget_status,
    build_closing_status,
    is_recurring_project,
)


def _project(**kw):
    base = dict(
        monthly_hours_budget=None,
        weekly_hours_budget=None,
        budget_hours=None,
        is_recurring=False,
        pricing_model=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_explicit_monthly_budget_wins():
    weekly, monthly = effective_budgets(_project(monthly_hours_budget=24, weekly_hours_budget=6))
    assert monthly == 24
    assert weekly == 6


def test_recurring_falls_back_to_budget_hours():
    weekly, monthly = effective_budgets(_project(is_recurring=True, budget_hours=40))
    assert monthly == 40
    # weekly derived from monthly (~4.33 weeks)
    assert weekly == round(40 / 4.33, 1)


def test_monthly_pricing_falls_back_to_budget_hours():
    weekly, monthly = effective_budgets(_project(pricing_model="monthly", budget_hours=20))
    assert monthly == 20


def test_non_recurring_does_not_derive_monthly_from_budget_hours():
    # budget_hours here is a life-of-project total, not a monthly ceiling
    weekly, monthly = effective_budgets(_project(pricing_model="project", budget_hours=80))
    assert monthly is None
    assert weekly is None


def test_explicit_weekly_not_overwritten():
    weekly, monthly = effective_budgets(
        _project(is_recurring=True, budget_hours=40, weekly_hours_budget=8)
    )
    assert monthly == 40
    assert weekly == 8


def test_build_status_thresholds():
    status = build_budget_status(10, 40, 8 * 60, 40 * 60)
    assert status["week"]["status"] == "warning"   # 8/10 = 80%
    assert status["month"]["status"] == "over"      # 40/40 = 100%


# --- closing status (puntual projects) ---

def _fixed_project(**kw):
    base = dict(
        is_recurring=False,
        pricing_model="project",
        budget_hours=None,
        target_end_date=None,
        start_date=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_no_closing_without_end_date():
    assert build_closing_status(_fixed_project(), 0, date(2026, 6, 24)) is None


def test_closing_soon_within_7_days():
    today = date(2026, 6, 24)
    p = _fixed_project(target_end_date=datetime(2026, 6, 29))  # 5 días
    c = build_closing_status(p, 0, today)
    assert c["days_left"] == 5
    assert c["overdue"] is False
    assert c["status"] == "warning"


def test_closing_overdue():
    today = date(2026, 6, 24)
    p = _fixed_project(target_end_date=datetime(2026, 6, 20))  # vencido
    c = build_closing_status(p, 0, today)
    assert c["overdue"] is True
    assert c["status"] == "over"


def test_closing_far_off_is_ok():
    today = date(2026, 6, 24)
    p = _fixed_project(target_end_date=datetime(2026, 9, 1))
    c = build_closing_status(p, 0, today)
    assert c["status"] == "ok"


def test_closing_hours_over_budget_is_over():
    today = date(2026, 6, 24)
    p = _fixed_project(target_end_date=datetime(2026, 9, 1), budget_hours=10)
    c = build_closing_status(p, 11 * 60, today)  # 11h de 10h
    assert c["status"] == "over"
    assert c["remaining_hours"] == -1.0


def test_closing_pace_risk_warns_even_when_far():
    today = date(2026, 6, 24)
    # 30 días totales, 3 transcurridos (10% del plazo) pero 70% de horas usadas
    p = _fixed_project(
        start_date=datetime(2026, 6, 21),
        target_end_date=datetime(2026, 7, 21),
        budget_hours=10,
    )
    c = build_closing_status(p, 7 * 60, today)
    assert c["pace_risk"] is True
    assert c["status"] == "warning"


def test_is_recurring_helper():
    assert is_recurring_project(_project(is_recurring=True)) is True
    assert is_recurring_project(_project(pricing_model="monthly")) is True
    assert is_recurring_project(_fixed_project()) is False

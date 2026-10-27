"""Arrastre de horas entre meses y aviso temprano al 75 %: reglas puras."""
from datetime import date, datetime
from types import SimpleNamespace

from backend.services.hours_carryover import month_budget, previous_month_start, started_before
from backend.services.incident_project_conditions import (
    MONTHLY_WARNING_RATIO,
    PROJECT_MONTHLY_HOURS_EXCEEDED,
    PROJECT_MONTHLY_HOURS_WARNING,
    _monthly_condition,
    hours_ratio,
    monthly_hours_usage,
)
from backend.services.time_budget import build_budget_status
from backend.startup import deployment_schema
from backend.startup.project_hours_carryover_schema import MIGRATION


def test_sobran_horas_se_suman_y_el_exceso_se_resta():
    assert month_budget(10, carryover=True, previous_minutes=360, eligible=True).budget == 14
    assert month_budget(10, carryover=True, previous_minutes=360, eligible=True).carried == 4
    over = month_budget(10, carryover=True, previous_minutes=840, eligible=True)
    assert (over.base, over.budget, over.carried) == (10, 6, -4)
    # El exceso se come como mucho el mes entero.
    assert month_budget(10, carryover=True, previous_minutes=1800, eligible=True).budget == 0


def test_sin_opcion_sin_techo_o_sin_mes_anterior_no_hay_arrastre():
    plain = month_budget(10, carryover=False, previous_minutes=0, eligible=True)
    assert (plain.budget, plain.carried) == (10, None)
    assert month_budget(10, carryover=True, previous_minutes=0, eligible=False).carried is None
    assert month_budget(None, carryover=True, previous_minutes=0, eligible=True).budget is None
    assert month_budget(0, carryover=True, previous_minutes=0, eligible=True).budget is None


def test_mes_anterior_y_proyecto_existente():
    assert previous_month_start(date(2026, 1, 1)) == date(2025, 12, 1)
    assert previous_month_start(date(2026, 3, 1)) == date(2026, 2, 1)
    month = date(2026, 10, 1)
    assert started_before(datetime(2026, 9, 30), None, month)  # noqa: DTZ001
    assert not started_before(datetime(2026, 10, 1), datetime(2020, 1, 1), month)  # noqa: DTZ001 - manda start_date
    assert started_before(None, datetime(2026, 9, 1), month)  # noqa: DTZ001
    assert not started_before(None, None, month)


def _row(**fields):
    base = dict(
        id=5, name="Retainer", monthly_hours_budget=10, weekly_hours_budget=None, is_recurring=True,
        pricing_model="monthly", budget_hours=None, month_minutes=0, hours_carryover=False,
        previous_month_minutes=0, carry_eligible=True,
    )
    base.update(fields)
    return SimpleNamespace(**base)


def test_aviso_temprano_al_75_y_alerta_al_100():
    assert MONTHLY_WARNING_RATIO == 0.75
    today = date(2026, 10, 20)
    assert _monthly_condition(_row(month_minutes=440), today) is None  # 73 %
    warning = _monthly_condition(_row(month_minutes=450), today)
    assert warning.kind == PROJECT_MONTHLY_HOURS_WARNING and warning.severity == "warning"
    assert warning.key == f"{PROJECT_MONTHLY_HOURS_WARNING}:project:5:2026-10"
    exceeded = _monthly_condition(_row(month_minutes=600), today)
    assert exceeded.kind == PROJECT_MONTHLY_HOURS_EXCEEDED and exceeded.severity == "critical"


def test_el_aviso_usa_el_techo_con_arrastre_y_lo_explica():
    today = date(2026, 10, 20)
    row = _row(month_minutes=600, hours_carryover=True, previous_month_minutes=360)  # 10 de 14
    assert monthly_hours_usage(row) == (10, 14)
    assert _monthly_condition(row, today) is None
    row = _row(month_minutes=480, hours_carryover=True, previous_month_minutes=0)  # 8 de 20 → nada
    assert _monthly_condition(row, today) is None
    row = _row(month_minutes=0, hours_carryover=True, previous_month_minutes=1800)  # el exceso se comió el mes
    condition = _monthly_condition(row, today)
    assert condition.kind == PROJECT_MONTHLY_HOURS_EXCEEDED and "sin margen" in condition.title
    assert hours_ratio(0, 0) == float("inf")


def test_la_extension_recibe_base_y_arrastre():
    status = build_budget_status(None, 12, 0, 60, month_base=10, month_carried=2)
    assert status["month"]["budget_hours"] == 12
    assert (status["month"]["base_budget_hours"], status["month"]["carried_hours"]) == (10, 2)
    eaten = build_budget_status(None, 0, 0, 60, month_base=10, month_carried=-12)
    assert eaten["month"]["status"] == "over" and eaten["month"]["remaining_hours"] == -1
    assert "carried_hours" not in build_budget_status(None, 10, 0, 60)["month"]


def test_la_migracion_esta_en_el_plan():
    assert MIGRATION in deployment_schema.MIGRATIONS

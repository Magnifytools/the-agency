"""Pendiente = backlog sin fecha; con la Planificada llegada, En curso (Nacho, 18 nov 2026).

Lo que importa: gana lo que la persona acaba de cambiar (fecha → En curso;
elegir Pendiente → se quita la fecha) y el panel, que manda el borrador entero,
no dispara la regla por mandar campos que no ha tocado.
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.db.models import TaskStatus
from backend.services import daily_facts, task_lifecycle
from backend.services.task_lifecycle import apply_planned_start

TODAY = date(2026, 11, 18)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(task_lifecycle, "business_today", lambda: TODAY)


def _task(status=TaskStatus.pending, scheduled=None, recurring=False):
    return SimpleNamespace(status=status, scheduled_date=scheduled, is_recurring=recurring)


def test_al_crear_con_fecha_de_hoy_o_pasada_nace_en_curso():
    for scheduled in (TODAY, TODAY - timedelta(days=3)):
        data = {"title": "x", "scheduled_date": scheduled}
        apply_planned_start(data)
        assert data["status"] == TaskStatus.in_progress
    data = {"title": "x", "status": TaskStatus.backlog, "scheduled_date": TODAY}
    apply_planned_start(data)
    assert data["status"] == TaskStatus.in_progress


def test_al_crear_con_fecha_futura_o_sin_fecha_sigue_pendiente():
    for data in ({"scheduled_date": TODAY + timedelta(days=1)}, {"scheduled_date": None}, {}):
        apply_planned_start(data)
        assert "status" not in data


def test_poner_la_fecha_de_hoy_a_una_pendiente_la_arranca():
    data = {"scheduled_date": TODAY}
    apply_planned_start(data, _task())
    assert data["status"] == TaskStatus.in_progress


def test_el_panel_manda_todo_y_gana_la_fecha_que_cambio():
    # Borrador entero: estado igual al guardado, fecha nueva.
    data = {"status": "pending", "scheduled_date": TODAY, "title": "x"}
    apply_planned_start(data, _task(scheduled=None))
    assert data["status"] == TaskStatus.in_progress


def test_elegir_pendiente_con_fecha_llegada_quita_la_fecha():
    data = {"status": TaskStatus.pending, "scheduled_date": TODAY}
    apply_planned_start(data, _task(status=TaskStatus.in_progress, scheduled=TODAY))
    assert data["status"] == TaskStatus.pending
    assert data["scheduled_date"] is None
    # Sólo el estado en el parche (tablero, en bloque): igual.
    data = {"status": TaskStatus.pending}
    apply_planned_start(data, _task(status=TaskStatus.in_progress, scheduled=TODAY - timedelta(days=2)))
    assert data["scheduled_date"] is None


def test_elegir_pendiente_con_fecha_futura_la_conserva():
    data = {"status": TaskStatus.pending}
    apply_planned_start(data, _task(status=TaskStatus.in_progress, scheduled=TODAY + timedelta(days=5)))
    assert "scheduled_date" not in data


def test_sin_cambiar_estado_ni_fecha_no_toca_nada():
    # Pendiente heredada con fecha pasada: la arregla la pasada de madrugada, no
    # una edición del título.
    data = {"status": "pending", "scheduled_date": TODAY - timedelta(days=1), "title": "otro"}
    apply_planned_start(data, _task(scheduled=TODAY - timedelta(days=1)))
    assert data["status"] == "pending"
    assert data["scheduled_date"] == TODAY - timedelta(days=1)


def test_nunca_en_plantillas_recurrentes_ni_otros_estados():
    data = {"scheduled_date": TODAY}
    apply_planned_start(data, _task(recurring=True))
    assert "status" not in data
    for status in (TaskStatus.waiting, TaskStatus.in_review, TaskStatus.completed, TaskStatus.in_progress):
        data = {"scheduled_date": TODAY}
        apply_planned_start(data, _task(status=status))
        assert "status" not in data


def _row(status, scheduled=None, due=None):
    return SimpleNamespace(status=status, scheduled_date=scheduled, due_date=due)


def test_cierre_en_curso_sale_siempre_y_sin_la_palabra_pendiente():
    day, tomorrow = TODAY, TODAY + timedelta(days=1)
    step = daily_facts._next_step
    assert step(_row(TaskStatus.in_progress), day, tomorrow) == ("in_progress", "En curso")
    assert step(_row(TaskStatus.in_progress, scheduled=day), day, tomorrow) == ("in_progress", "En curso")
    assert step(_row(TaskStatus.in_progress, scheduled=day - timedelta(days=1)), day, tomorrow)[1] == (
        "Planificada el 2026-11-17"
    )
    assert step(_row(TaskStatus.in_progress, scheduled=tomorrow), day, tomorrow)[1] == "Planificada para 2026-11-19"
    assert step(
        _row(TaskStatus.in_review, due=datetime(2026, 11, 10)), day, tomorrow,  # noqa: DTZ001
    )[1] == "Vencida el 2026-11-10"
    # En revisión, como antes: sólo con fecha hasta mañana.
    assert step(_row(TaskStatus.in_review), day, tomorrow) is None
    # Avanzada hoy: ya sale como "avanzada"; no se repite como "En curso".
    assert step(_row(TaskStatus.advanced), day, tomorrow) is None


def test_pendiente_no_es_trabajo_del_cierre():
    assert TaskStatus.pending not in daily_facts._OPEN_WORK
    assert TaskStatus.backlog not in daily_facts._OPEN_WORK
    assert TaskStatus.waiting not in daily_facts._OPEN_WORK

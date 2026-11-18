"""Integración: Pendiente = backlog sin fecha; con la Planificada llegada, En curso.

Criterio de Nacho (18 nov 2026), contra PostgreSQL real: la regla en las
escrituras (panel, Mi agenda, bloque), la pasada de las 00:01 y el cierre del
día, que ya no cuenta las pendientes y sí todo lo que está En curso.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.db.models import Task, TaskStatus
from backend.services.daily_facts import collect_daily_facts
from backend.services.temporal import business_today


async def _tarea(db_session, user_id, **fields):
    task = Task(title=fields.pop("title", "Tarea"), assigned_to=user_id, **fields)
    db_session.add(task)
    await db_session.flush()
    return task


def _sesion_de_prueba(monkeypatch, db_session):
    import backend.db.database as db_module

    class _Shim:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(db_module, "async_session", lambda: _Shim())


@pytest.mark.asyncio
async def test_crear_con_fecha_de_hoy_nace_en_curso(admin_client):
    today = business_today()
    resp = await admin_client.post(
        "/api/tasks", json={"title": "Empieza hoy", "scheduled_date": today.isoformat()},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "in_progress"

    resp = await admin_client.post(
        "/api/tasks",
        json={"title": "Empieza mañana", "scheduled_date": (today + timedelta(days=1)).isoformat()},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_planificar_hoy_una_pendiente_la_pone_en_curso(admin_client, db_session):
    task = await _tarea(db_session, admin_client.test_user.id, status=TaskStatus.pending)
    resp = await admin_client.put(
        f"/api/tasks/{task.id}", json={"scheduled_date": business_today().isoformat()},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_planificar_para_hoy_en_bloque_tambien(admin_client, db_session):
    task = await _tarea(db_session, admin_client.test_user.id, status=TaskStatus.backlog)
    resp = await admin_client.patch(
        "/api/tasks/bulk/update",
        json={"ids": [task.id], "updates": {"scheduled_date": business_today().isoformat()}},
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(task)
    assert task.status == TaskStatus.in_progress


@pytest.mark.asyncio
async def test_elegir_pendiente_con_fecha_de_hoy_la_devuelve_al_backlog(admin_client, db_session):
    today = business_today()
    task = await _tarea(
        db_session, admin_client.test_user.id, status=TaskStatus.in_progress, scheduled_date=today,
    )
    resp = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "pending"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["scheduled_date"] is None


@pytest.mark.asyncio
async def test_la_pasada_de_madrugada_arranca_las_del_dia(db_session, admin_user, monkeypatch):
    from backend.startup.background_tasks import _daily_task_status_rollover

    today = business_today()
    hoy = await _tarea(db_session, admin_user.id, status=TaskStatus.pending, scheduled_date=today)
    ayer = await _tarea(
        db_session, admin_user.id, status=TaskStatus.backlog, scheduled_date=today - timedelta(days=1),
    )
    manana = await _tarea(
        db_session, admin_user.id, status=TaskStatus.pending, scheduled_date=today + timedelta(days=1),
    )
    sin_fecha = await _tarea(db_session, admin_user.id, status=TaskStatus.pending)
    plantilla = await _tarea(
        db_session, admin_user.id, status=TaskStatus.pending, scheduled_date=today,
        is_recurring=True, recurrence_pattern="daily",
    )

    _sesion_de_prueba(monkeypatch, db_session)
    await _daily_task_status_rollover()

    for task in (hoy, ayer, manana, sin_fecha, plantilla):
        await db_session.refresh(task)
    assert hoy.status == TaskStatus.in_progress
    assert ayer.status == TaskStatus.in_progress
    assert manana.status == TaskStatus.pending
    assert sin_fecha.status == TaskStatus.pending
    assert plantilla.status == TaskStatus.pending, "una plantilla recurrente no arranca"


@pytest.mark.asyncio
async def test_el_cierre_no_cuenta_pendientes_y_si_lo_que_esta_en_curso(db_session, admin_user):
    day = business_today()
    tomorrow = day + timedelta(days=1)
    pendiente_manana = await _tarea(
        db_session, admin_user.id, title="Pendiente mañana",
        status=TaskStatus.pending, scheduled_date=tomorrow,
    )
    pendiente_vence = await _tarea(
        db_session, admin_user.id, title="Pendiente que vence",
        status=TaskStatus.pending, due_date=day,
    )
    en_curso = await _tarea(db_session, admin_user.id, title="En curso sin fecha", status=TaskStatus.in_progress)
    espera = await _tarea(
        db_session, admin_user.id, title="En espera",
        status=TaskStatus.waiting, waiting_for="Diseño", follow_up_date=tomorrow,
    )

    result = await collect_daily_facts(db_session, admin_user, day)
    by_task = {}
    for fact in result["facts"]:
        by_task.setdefault(fact["task_id"], []).append(fact)

    assert pendiente_manana.id not in by_task
    assert pendiente_vence.id not in by_task
    assert [(f["kind"], f["detail"]) for f in by_task[en_curso.id]] == [("next_step", "En curso")]
    assert by_task[espera.id][0]["kind"] == "task_waiting"
    assert all("Pendiente" not in (f["detail"] or "") for f in result["facts"])

    saved = (await db_session.execute(select(Task).where(Task.id == en_curso.id))).scalar_one()
    assert saved.status == TaskStatus.in_progress, "leer el cierre no cambia estados"

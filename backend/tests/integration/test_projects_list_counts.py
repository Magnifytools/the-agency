"""Integración: contadores del listado de proyectos contra PostgreSQL real.

`GET /api/proyects` cargaba las tareas de cada proyecto (`selectinload(
Project.tasks).selectinload(Task.assigned_user)`) solo para hacer `len()` y un
`sum()`. Con 11 proyectos y 725 tareas en producción eso materializaba la tabla
entera de tareas con su join de usuarios: 449 ms de servidor de media, el
endpoint humano más lento de la aplicación.

Ahora los contadores se agregan en la base de datos. Estos tests van contra
Postgres de verdad **a propósito**: la suite unitaria mockea `get_db`, así que
un `GROUP BY` mal construido o un `case()` inválido pasaría desapercibido ahí y
reventaría en producción, en el listado que se abre 1.519 veces por trimestre.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.db.models import (
    Client,
    Project,
    ProjectPhase,
    ProjectStatus,
    Task,
    TaskStatus,
)


async def _seed(db_session, *, tareas_por_estado: dict, fases: int = 0):
    """Crea un proyecto con tareas en los estados dados y N fases."""
    client = Client(name="Cliente contadores")
    db_session.add(client)
    await db_session.flush()

    project = Project(
        name="Proyecto contadores",
        client_id=client.id,
        status=ProjectStatus.active,
    )
    db_session.add(project)
    await db_session.flush()

    for estado, cuantas in tareas_por_estado.items():
        for i in range(cuantas):
            db_session.add(
                Task(
                    title=f"{estado.value}-{i}",
                    project_id=project.id,
                    client_id=client.id,
                    status=estado,
                )
            )
    for i in range(fases):
        db_session.add(ProjectPhase(name=f"Fase {i}", project_id=project.id))

    await db_session.commit()
    return project


def _find(payload, project_id):
    for item in payload["items"]:
        if item["id"] == project_id:
            return item
    raise AssertionError(f"proyecto {project_id} ausente del listado")


@pytest.mark.asyncio
async def test_contadores_coinciden_con_la_base_de_datos(admin_client, db_session):
    project = await _seed(
        db_session,
        tareas_por_estado={
            TaskStatus.completed: 7,
            TaskStatus.in_progress: 2,
            TaskStatus.pending: 3,
        },
        fases=4,
    )

    resp = await admin_client.get("/api/projects")
    assert resp.status_code == 200, resp.text

    item = _find(resp.json(), project.id)
    assert item["task_count"] == 12
    assert item["completed_task_count"] == 7
    assert item["phase_count"] == 4


@pytest.mark.asyncio
async def test_proyecto_sin_tareas_devuelve_ceros(admin_client, db_session):
    """El GROUP BY no devuelve fila para un proyecto sin tareas: debe dar 0.

    Este es justo el caso que un `dict[pid]` sin default habría roto con un
    KeyError, y el que la versión con `len(p.tasks)` resolvía sola.
    """
    project = await _seed(db_session, tareas_por_estado={}, fases=0)

    resp = await admin_client.get("/api/projects")
    assert resp.status_code == 200, resp.text

    item = _find(resp.json(), project.id)
    assert item["task_count"] == 0
    assert item["completed_task_count"] == 0
    assert item["phase_count"] == 0


@pytest.mark.asyncio
async def test_ningun_proyecto_no_revienta(admin_client):
    """`.in_([])` con lista vacía: el atajo de _list_counts debe cubrirlo."""
    resp = await admin_client.get("/api/projects", params={"status": "cancelled"})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_contadores_no_se_mezclan_entre_proyectos(admin_client, db_session):
    """Un GROUP BY mal agrupado sumaría las tareas de todos los proyectos."""
    a = await _seed(db_session, tareas_por_estado={TaskStatus.completed: 5}, fases=1)
    b = await _seed(db_session, tareas_por_estado={TaskStatus.pending: 2}, fases=3)

    resp = await admin_client.get("/api/projects")
    payload = resp.json()

    item_a, item_b = _find(payload, a.id), _find(payload, b.id)
    assert (item_a["task_count"], item_a["completed_task_count"]) == (5, 5)
    assert (item_b["task_count"], item_b["completed_task_count"]) == (2, 0)
    assert item_a["phase_count"] == 1
    assert item_b["phase_count"] == 3


@pytest.mark.asyncio
async def test_el_listado_expone_monthly_fee(admin_client, db_session):
    """La tarifa es la fuente de verdad del pricing y no viajaba en el listado."""
    client = Client(name="Cliente tarifa")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Proyecto con tarifa",
        client_id=client.id,
        status=ProjectStatus.active,
        pricing_model="monthly",
        monthly_fee=2300,
    )
    db_session.add(project)
    await db_session.commit()

    resp = await admin_client.get("/api/projects")
    item = _find(resp.json(), project.id)
    assert item["monthly_fee"] == 2300.0
    assert item["pricing_model"] == "monthly"


@pytest.mark.asyncio
async def test_las_tareas_ya_no_se_cargan_para_contar(admin_client, db_session):
    """La regresión que importa: que no vuelva el eager load.

    Se cuentan los SELECT que la petición lanza contra `tasks`. Con el eager
    load original había uno que traía las filas y otro para `assigned_user`;
    con la agregación debe haber exactamente uno, y con COUNT dentro.
    """
    await _seed(
        db_session,
        tareas_por_estado={TaskStatus.completed: 30, TaskStatus.pending: 20},
        fases=2,
    )

    consultas: list[str] = []

    from sqlalchemy import event

    engine = db_session.get_bind().engine

    def _capture(conn, cursor, statement, parameters, context, executemany):
        consultas.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        resp = await admin_client.get("/api/projects")
        assert resp.status_code == 200, resp.text
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    sobre_tasks = [q for q in consultas if "FROM tasks" in q]
    assert len(sobre_tasks) == 1, f"esperaba 1 query sobre tasks, hubo {len(sobre_tasks)}:\n" + "\n".join(sobre_tasks)
    assert "count(" in sobre_tasks[0].lower(), sobre_tasks[0]
    # Y ninguna debe traerse los usuarios asignados.
    assert not any("FROM users" in q and "tasks" in q for q in consultas)

"""Undo end-to-end contra Postgres real.

La suite unitaria mockea ``get_db``, así que allí no se ejecuta SQL y los
eventos ORM del journal no llegan a dispararse: la captura sólo se puede
demostrar aquí. Se cubre el ciclo completo — hacer el cambio por HTTP, ver la
entrada del journal, deshacerla y comprobar el estado de la fila.

La entrada se persiste en la misma transacción real que el cambio. Estas
pruebas leen change_logs; no sustituyen el escritor ni reconstruyen filas.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Client,
    ClientStatus,
    Project,
    Task,
    TaskChecklist,
    TaskPriority,
    TaskStatus,
    TimeEntry,
    User,
    UserRole,
)
from backend.services import change_journal as cj

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def journal(db_session, admin_user):
    from backend.db.models import ChangeLog
    cj.set_actor(None)
    seen = set((await db_session.scalars(select(ChangeLog.id))).all())

    class _Journal:
        actor_id = admin_user.id

        async def rows(self):
            rows = (await db_session.scalars(select(ChangeLog).order_by(ChangeLog.id))).all()
            return [row for row in rows if row.id not in seen]

        async def peek(self):
            return [{"operations": row.operations} for row in await self.rows()]

        async def entries(self):
            rows = await self.rows()
            seen.update(row.id for row in rows)
            return rows

        async def only(self):
            rows = await self.entries()
            assert len(rows) == 1, f"esperaba una entrada, hay {len(rows)}"
            return rows[0]

    try:
        yield _Journal()
    finally:
        cj.set_actor(None)


@pytest_asyncio.fixture
async def base_client(db_session):
    """Cliente de apoyo, creado sin actor: no debe aparecer en el journal."""
    client = Client(name="Acme Undo", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    return client


async def _make_task(db_session, base_client, **kwargs) -> Task:
    task = Task(
        title=kwargs.pop("title", "Tarea de partida"),
        status=kwargs.pop("status", TaskStatus.pending),
        priority=kwargs.pop("priority", TaskPriority.medium),
        client_id=base_client.id,
        **kwargs,
    )
    db_session.add(task)
    await db_session.flush()
    return task


# ── Captura ──────────────────────────────────────────────────────────────────

async def test_un_cambio_sin_actor_no_entra_en_el_journal(db_session, base_client, journal):
    """El barrido nocturno y los scripts no deben llenar el historial de nadie."""
    task = await _make_task(db_session, base_client)
    task.status = TaskStatus.completed
    await db_session.commit()

    assert (await journal.peek()) == []


async def test_crear_una_tarea_por_http_deja_una_entrada(admin_client, base_client, journal):
    resp = await admin_client.post("/api/tasks", json={
        "title": "Revisar sitemap", "client_id": base_client.id, "priority": "high",
    })
    assert resp.status_code == 201, resp.text

    entry = await journal.only()
    assert entry.entity_type == "task"
    assert entry.entity_id == resp.json()["id"]
    assert entry.action == "create"
    assert entry.label == "Tarea «Revisar sitemap» creada"


# ── Deshacer ────────────────────────────────────────────────────────────────

async def test_deshacer_una_creacion_borra_la_fila(admin_client, db_session, base_client, journal):
    task_id = (await admin_client.post("/api/tasks", json={
        "title": "Se va a deshacer", "client_id": base_client.id,
    })).json()["id"]
    entry = await journal.only()

    resp = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert resp.status_code == 200, resp.text
    assert resp.json()["restored"] == 1

    assert await db_session.get(Task, task_id) is None


async def test_deshacer_una_edicion_devuelve_los_valores_anteriores(
    admin_client, db_session, base_client, journal
):
    task = await _make_task(db_session, base_client, title="Título viejo",
                            status=TaskStatus.pending)
    await db_session.commit()

    resp = await admin_client.put(f"/api/tasks/{task.id}", json={
        "title": "Título nuevo", "status": "completed",
    })
    assert resp.status_code == 200, resp.text
    entry = await journal.only()
    assert entry.action == "update"

    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200

    await db_session.refresh(task)
    assert task.title == "Título viejo"
    assert task.status == TaskStatus.pending


async def test_deshacer_ajuste_manual_restaura_tarea_y_entrada(
    admin_client, db_session, base_client, journal
):
    task = await _make_task(db_session, base_client, actual_minutes=None)
    await db_session.commit()
    response = await admin_client.put(
        f"/api/tasks/{task.id}", json={"actual_minutes": 45}
    )
    assert response.status_code == 200, response.text
    entry = await journal.only()
    assert {op["entity_type"] for op in entry.operations} == {"task", "time_entry"}

    undone = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert undone.status_code == 200, undone.text
    await db_session.refresh(task)
    assert task.actual_minutes is None, (entry.operations, undone.json())
    assert not (await db_session.execute(
        select(TimeEntry).where(TimeEntry.task_id == task.id)
    )).scalars().all()


async def test_conflicto_manual_no_deja_total_falso(
    admin_client, db_session, base_client, journal
):
    task = await _make_task(db_session, base_client, actual_minutes=None)
    await db_session.commit()
    await admin_client.put(f"/api/tasks/{task.id}", json={"actual_minutes": 45})
    entry = await journal.only()
    manual = (await db_session.execute(
        select(TimeEntry).where(TimeEntry.task_id == task.id)
    )).scalar_one()

    cj.set_actor(None)
    manual.minutes = 60
    task.actual_minutes = 60
    await db_session.commit()
    undone = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert undone.status_code == 409
    await db_session.refresh(entry)
    assert entry.undone_at is None
    await db_session.refresh(task)
    await db_session.refresh(manual)
    assert task.actual_minutes == manual.minutes == 60


async def test_deshacer_manual_recalcula_si_aparece_tiempo_de_timer(
    admin_client, db_session, base_client, journal
):
    task = await _make_task(db_session, base_client, actual_minutes=None)
    await db_session.commit()
    assert (await admin_client.put(
        f"/api/tasks/{task.id}", json={"actual_minutes": 45}
    )).status_code == 200
    entry = await journal.only()

    cj.set_actor(None)
    db_session.add(TimeEntry(
        task_id=task.id, user_id=admin_client.test_user.id, minutes=10,
        date=datetime(2026, 9, 17, 9, 0), notes="timer",
    ))
    await db_session.commit()

    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200
    await db_session.refresh(task)
    assert task.actual_minutes == 10


async def test_crear_tarea_con_horas_y_deshacer_borra_entrada_manual(
    admin_client, db_session, base_client, journal
):
    response = await admin_client.post("/api/tasks", json={
        "title": "Con horas", "client_id": base_client.id, "actual_minutes": 25,
    })
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    entry = await journal.only()
    assert {op["entity_type"] for op in entry.operations} == {"task", "time_entry"}
    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200
    assert await db_session.get(Task, task_id) is None
    assert not (await db_session.execute(
        select(TimeEntry).where(TimeEntry.task_id == task_id)
    )).scalars().all()


async def test_deshacer_edicion_de_ajuste_manual_conserva_fecha(
    admin_client, db_session, base_client, journal
):
    task = await _make_task(db_session, base_client, actual_minutes=30)
    manual = TimeEntry(
        task_id=task.id,
        user_id=admin_client.test_user.id,
        minutes=30,
        date=datetime(2026, 9, 1, 9, 0),
        notes="[manual]",
    )
    db_session.add(manual)
    await db_session.commit()
    original_date = manual.date

    assert (await admin_client.put(
        f"/api/tasks/{task.id}", json={"actual_minutes": 50}
    )).status_code == 200
    entry = await journal.only()
    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200
    await db_session.refresh(task)
    await db_session.refresh(manual)
    assert task.actual_minutes == 30
    assert manual.minutes == 30
    assert manual.date == original_date


async def test_deshacer_edicion_manual_suma_tiempo_nuevo_de_timer(
    admin_client, db_session, base_client, journal
):
    task = await _make_task(db_session, base_client, actual_minutes=60)
    manual = TimeEntry(
        task_id=task.id, user_id=admin_client.test_user.id, minutes=60,
        date=datetime(2026, 9, 1, 9, 0), notes="[manual]",
    )
    db_session.add(manual)
    await db_session.commit()
    assert (await admin_client.put(
        f"/api/tasks/{task.id}", json={"actual_minutes": 90}
    )).status_code == 200
    entry = await journal.only()
    cj.set_actor(None)
    db_session.add(TimeEntry(
        task_id=task.id, user_id=admin_client.test_user.id, minutes=10,
        date=datetime(2026, 9, 17, 9, 0), notes="timer",
    ))
    await db_session.commit()
    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200
    await db_session.refresh(task)
    assert task.actual_minutes == 70


async def test_deshacer_un_borrado_reinserta_la_tarea_con_su_id_y_su_checklist(
    admin_client, db_session, base_client, journal
):
    """El checklist se borra en cascada: si el undo no lo repone, es pérdida silenciosa."""
    task = await _make_task(db_session, base_client, title="Con checklist")
    db_session.add(TaskChecklist(task_id=task.id, text="Paso 1", order_index=0))
    db_session.add(TaskChecklist(task_id=task.id, text="Paso 2", order_index=1))
    await db_session.commit()
    task_id = task.id

    assert (await admin_client.delete(f"/api/tasks/{task_id}")).status_code == 204
    entry = await journal.only()
    assert entry.action == "delete"
    assert {op["entity_type"] for op in entry.operations} == {"task", "task_checklist"}

    resp = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert resp.status_code == 200, resp.text

    restored = await db_session.get(Task, task_id)
    assert restored is not None
    assert restored.title == "Con checklist"

    from sqlalchemy import select
    items = (await db_session.execute(
        select(TaskChecklist).where(TaskChecklist.task_id == task_id)
    )).scalars().all()
    assert sorted(i.text for i in items) == ["Paso 1", "Paso 2"]


async def test_borrar_un_proyecto_y_deshacerlo_devuelve_tambien_sus_tareas(
    admin_client, db_session, base_client, journal
):
    """Un borrado que desvincula tareas es UNA acción, y se deshace de una vez."""
    project = Project(name="Rediseño", client_id=base_client.id)
    db_session.add(project)
    await db_session.flush()
    task = await _make_task(db_session, base_client, title="Tarea del proyecto",
                            project_id=project.id)
    await db_session.commit()
    project_id, task_id = project.id, task.id

    assert (await admin_client.delete(f"/api/projects/{project_id}")).status_code == 204
    entry = await journal.only()
    assert entry.entity_type == "project"
    assert entry.label == "Proyecto «Rediseño» eliminado"

    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200

    assert await db_session.get(Project, project_id) is not None
    await db_session.refresh(task)
    assert task.project_id == project_id


async def test_desactivar_un_cliente_es_un_update_y_se_deshace(
    admin_client, db_session, base_client, journal
):
    """DELETE /api/clients/{id} es soft delete: el undo lo devuelve a activo."""
    assert (await admin_client.delete(f"/api/clients/{base_client.id}")).status_code == 200
    entry = await journal.only()
    assert entry.action == "update"

    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200
    await db_session.refresh(base_client)
    assert base_client.status == ClientStatus.active


# ── Conflictos y límites ────────────────────────────────────────────────────

async def test_no_pisa_una_columna_que_otro_cambio_despues(
    admin_client, db_session, base_client, journal
):
    task = await _make_task(db_session, base_client, title="Original",
                            status=TaskStatus.pending)
    await db_session.commit()

    await admin_client.put(f"/api/tasks/{task.id}", json={
        "title": "Editado por mí", "status": "completed",
    })
    entry = await journal.only()

    # Alguien toca el título después (sin actor: no genera entrada propia).
    cj.set_actor(None)
    await db_session.refresh(task)
    task.title = "Lo cambió otra persona"
    await db_session.commit()

    resp = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert resp.status_code == 200, resp.text
    assert any("title" in w for w in resp.json()["warnings"])

    await db_session.refresh(task)
    assert task.title == "Lo cambió otra persona"   # respetado
    assert task.status == TaskStatus.pending        # restaurado


async def test_undo_create_rejects_later_edit_instead_of_deleting_it(
    admin_client, make_member_client, db_session, base_client, journal
):
    task_id = (await admin_client.post("/api/tasks", json={
        "title": "Creada por A", "client_id": base_client.id,
    })).json()["id"]
    entry = await journal.only()

    # A distinct actor B edits after A's creation. The inverse must preserve it.
    other = await make_member_client([("tasks", True, True)])
    try:
        edited = await other.put(f"/api/tasks/{task_id}", json={"title": "Editada por B"})
        assert edited.status_code == 200, edited.text
    finally:
        await other.aclose()
    task = await db_session.get(Task, task_id)

    response = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert response.status_code == 409, response.text
    assert "cambió después" in response.json()["detail"]
    await db_session.refresh(task)
    assert task.title == "Editada por B"
    await db_session.refresh(entry)
    assert entry.undone_at is None


async def test_undo_create_rejects_child_added_later_even_if_parent_is_unchanged(
    admin_client, db_session, base_client, journal
):
    task_id = (await admin_client.post("/api/tasks", json={
        "title": "Padre intacto", "client_id": base_client.id,
    })).json()["id"]
    entry = await journal.only()
    cj.set_actor(None)
    child = TaskChecklist(task_id=task_id, text="Trabajo posterior", order_index=0)
    db_session.add(child)
    await db_session.commit()

    response = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert response.status_code == 409, response.text
    assert "trabajo añadido después" in response.json()["detail"]
    assert await db_session.get(Task, task_id) is not None
    assert await db_session.get(TaskChecklist, child.id) is not None


async def test_undo_create_detects_later_change_from_a_column_default(
    admin_client, db_session, base_client, journal
):
    task_id = (await admin_client.post("/api/tasks", json={
        "title": "Default real", "client_id": base_client.id,
    })).json()["id"]
    entry = await journal.only()
    assert entry.operations[0]["after"]["is_inbox"] is False
    cj.set_actor(None)
    task = await db_session.get(Task, task_id)
    task.is_inbox = True
    await db_session.commit()

    response = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert response.status_code == 409, response.text
    assert "is_inbox" in response.json()["detail"]
    await db_session.refresh(task)
    assert task.is_inbox is True


async def test_project_numeric_roundtrip_create_update_delete_and_conflict(
    admin_client, db_session, base_client, journal,
):
    created = await admin_client.post("/api/projects", json={
        "name": "Numeric create", "client_id": base_client.id, "monthly_fee": 50.5,
    })
    assert created.status_code == 201, created.text
    created_id = created.json()["id"]
    create_change = await journal.only()
    assert create_change.operations[0]["after"]["monthly_fee"] == "50.50"
    # P21 alcanzó a guardar NUMERIC como JSON number antes de esta
    # canonización. Ese snapshot durable también debe seguir siendo deshacible.
    legacy_operations = [dict(operation) for operation in create_change.operations]
    legacy_operations[0] = {
        **legacy_operations[0],
        "after": {**legacy_operations[0]["after"], "monthly_fee": 50.5},
    }
    create_change.operations = legacy_operations
    await db_session.commit()
    undone = await admin_client.post(f"/api/changes/{create_change.id}/undo")
    assert undone.status_code == 200, undone.text
    assert await db_session.get(Project, created_id) is None

    cj.set_actor(None)
    project = Project(
        name="Numeric update/delete", client_id=base_client.id,
        monthly_fee=Decimal("10.10"),
    )
    db_session.add(project)
    await db_session.commit()
    project_id = project.id
    updated = await admin_client.put(f"/api/projects/{project_id}", json={"monthly_fee": 50.5})
    assert updated.status_code == 200, updated.text
    update_change = await journal.only()
    assert update_change.operations[0]["after"]["monthly_fee"] == "50.50"
    undone = await admin_client.post(f"/api/changes/{update_change.id}/undo")
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).monthly_fee == Decimal("10.10")

    deleted = await admin_client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204, deleted.text
    delete_change = await journal.only()
    assert delete_change.operations[0]["before"]["monthly_fee"] == "10.10"
    undone = await admin_client.post(f"/api/changes/{delete_change.id}/undo")
    assert undone.status_code == 200, undone.text
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).monthly_fee == Decimal("10.10")

    changed = await admin_client.post("/api/projects", json={
        "name": "Numeric later edit", "client_id": base_client.id, "monthly_fee": 50.5,
    })
    assert changed.status_code == 201, changed.text
    changed_id = changed.json()["id"]
    changed_create = await journal.only()
    cj.set_actor(None)
    changed_project = await db_session.get(Project, changed_id)
    changed_project.monthly_fee = Decimal("50.51")
    await db_session.commit()

    rejected = await admin_client.post(f"/api/changes/{changed_create.id}/undo")
    assert rejected.status_code == 409, rejected.text
    assert "monthly_fee" in rejected.json()["detail"]
    db_session.expire_all()
    assert (await db_session.get(Project, changed_id)).monthly_fee == Decimal("50.51")


@pytest.mark.parametrize(("value", "persisted"), [
    (2.675, Decimal("2.67")),
    (1.005, Decimal("1.00")),
    (-2.675, Decimal("-2.67")),
    (-1.005, Decimal("-1.00")),
    (-0.0, Decimal("0.00")),
    (-0.001, Decimal("0.00")),
])
async def test_numeric_snapshot_matches_postgres_float_binding(
    value, persisted, admin_client, db_session, base_client, journal,
):
    created = await admin_client.post("/api/projects", json={
        "name": f"Float boundary {value}",
        "client_id": base_client.id,
        "monthly_fee": value,
    })
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    change = await journal.only()
    change_id = change.id
    snapshot_fee = change.operations[0]["after"]["monthly_fee"]
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).monthly_fee == persisted
    assert snapshot_fee == format(persisted, ".2f")

    undone = await admin_client.post(f"/api/changes/{change_id}/undo")
    assert undone.status_code == 200, undone.text
    assert await db_session.get(Project, project_id) is None


async def test_legacy_numeric_float_before_restores_persisted_value(
    admin_client, db_session, base_client, journal,
):
    """Legacy JSON numbers restore through PostgreSQL's float8 boundary."""
    created = await admin_client.post("/api/projects", json={
        "name": "Legacy numeric before",
        "client_id": base_client.id,
        "monthly_fee": 2.675,
    })
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    await journal.only()

    updated = await admin_client.put(
        f"/api/projects/{project_id}", json={"monthly_fee": 9.0},
    )
    assert updated.status_code == 200, updated.text
    update_change = await journal.only()
    update_operations = [dict(operation) for operation in update_change.operations]
    update_operations[0] = {
        **update_operations[0],
        "before": {**update_operations[0]["before"], "monthly_fee": 2.675},
    }
    update_change.operations = update_operations
    update_change_id = update_change.id
    await db_session.commit()

    undone_update = await admin_client.post(f"/api/changes/{update_change_id}/undo")
    assert undone_update.status_code == 200, undone_update.text
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).monthly_fee == Decimal("2.67")

    deleted = await admin_client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204, deleted.text
    delete_change = await journal.only()
    delete_operations = [dict(operation) for operation in delete_change.operations]
    delete_operations[0] = {
        **delete_operations[0],
        "before": {**delete_operations[0]["before"], "monthly_fee": 2.675},
    }
    delete_change.operations = delete_operations
    delete_change_id = delete_change.id
    await db_session.commit()

    undone_delete = await admin_client.post(f"/api/changes/{delete_change_id}/undo")
    assert undone_delete.status_code == 200, undone_delete.text
    db_session.expire_all()
    assert (await db_session.get(Project, project_id)).monthly_fee == Decimal("2.67")


async def test_time_entry_only_undo_locks_task_before_time_entry(
    admin_client, db_session, engine, base_client
):
    """Even a notes-only entry journal follows the shared Task→TimeEntry order."""
    from sqlalchemy import event
    from backend.db.models import ChangeLog

    task = await _make_task(db_session, base_client, actual_minutes=15)
    time_entry = TimeEntry(
        task_id=task.id,
        user_id=admin_client.test_user.id,
        minutes=15,
        date=datetime(2026, 9, 17, 9, 0),
        notes="después",
    )
    db_session.add(time_entry)
    await db_session.flush()
    change = ChangeLog(
        user_id=admin_client.test_user.id,
        entity_type="time_entry",
        entity_id=time_entry.id,
        action="update",
        label="Tiempo editado",
        operations=[{
            "entity_type": "time_entry",
            "entity_id": time_entry.id,
            "action": "update",
            "name": "Tiempo editado",
            "before": {"notes": "antes"},
            "after": {"notes": "después"},
        }],
    )
    db_session.add(change)
    await db_session.commit()

    locked_tables: list[str] = []

    def record_lock(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lower()
        if "for update" in sql:
            if "from tasks" in sql:
                locked_tables.append("task")
            elif "from time_entries" in sql:
                locked_tables.append("time_entry")

    event.listen(engine.sync_engine, "before_cursor_execute", record_lock)
    try:
        response = await admin_client.post(f"/api/changes/{change.id}/undo")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_lock)

    assert response.status_code == 200, response.text
    assert "task" in locked_tables and "time_entry" in locked_tables, locked_tables
    assert locked_tables.index("task") < locked_tables.index("time_entry"), locked_tables
    await db_session.refresh(time_entry)
    assert time_entry.notes == "antes"


async def test_project_edit_started_during_undo_wins_after_locked_conflict_check(
    engine, monkeypatch
):
    """A concurrent writer waits for Undo's row lock, then commits last."""
    from backend.api.routes import changes as changes_route
    from backend.core.security import hash_password
    from backend.db.models import ChangeLog
    from uuid import uuid4

    ids = {}
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            actor = User(email=f"undo-lock-{uuid4()}@test.local", full_name="Undo Lock",
                         hashed_password=hash_password("unused"), role=UserRole.admin, is_active=True)
            client = Client(name="Undo Lock Client", status=ClientStatus.active)
            setup.add_all([actor, client])
            await setup.commit()
            project = Project(name="Original", client_id=client.id)
            setup.add(project)
            await setup.commit()
            cj.set_actor(actor.id)
            project.name = "Editado por A"
            await setup.commit()
            change = await setup.scalar(select(ChangeLog).where(
                ChangeLog.user_id == actor.id, ChangeLog.entity_type == "project",
            ).order_by(ChangeLog.id.desc()))
            ids.update(user=actor.id, client=client.id, project=project.id, change=change.id)

        locked = asyncio.Event()
        release = asyncio.Event()
        original_undo_update = changes_route._undo_update

        async def paused_undo_update(*args, **kwargs):
            locked.set()
            await release.wait()
            return await original_undo_update(*args, **kwargs)

        monkeypatch.setattr(changes_route, "_undo_update", paused_undo_update)
        actor_view = SimpleNamespace(id=ids["user"], role=UserRole.admin, permissions=[])

        async with AsyncSession(engine, expire_on_commit=False) as undo_db, AsyncSession(engine) as edit_db:
            undo_task = asyncio.create_task(changes_route.undo_change(
                ids["change"], db=undo_db, current_user=actor_view,
            ))
            await asyncio.wait_for(locked.wait(), timeout=2)
            other_project = await edit_db.get(Project, ids["project"])
            other_project.name = "Editado por B"
            edit_task = asyncio.create_task(edit_db.commit())
            await asyncio.sleep(0.1)
            assert not edit_task.done(), "el editor concurrente no esperó el bloqueo de Undo"
            release.set()
            await undo_task
            await asyncio.wait_for(edit_task, timeout=2)

        async with AsyncSession(engine) as reader:
            assert await reader.scalar(select(Project.name).where(Project.id == ids["project"])) == "Editado por B"
    finally:
        cj.set_actor(None)
        if ids:
            async with AsyncSession(engine) as cleanup:
                await cleanup.execute(delete(ChangeLog).where(ChangeLog.user_id == ids["user"]))
                await cleanup.execute(delete(Project).where(Project.id == ids["project"]))
                await cleanup.execute(delete(Client).where(Client.id == ids["client"]))
                await cleanup.execute(delete(User).where(User.id == ids["user"]))
                await cleanup.commit()


async def test_deshacer_no_se_registra_como_cambio_nuevo(
    admin_client, base_client, journal
):
    """Si el undo se registrara, el historial sería un bucle deshacer/rehacer."""
    await admin_client.post("/api/tasks", json={"title": "Una", "client_id": base_client.id})
    entry = await journal.only()

    await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert (await journal.peek()) == []


async def test_no_se_puede_deshacer_dos_veces(admin_client, base_client, journal):
    await admin_client.post("/api/tasks", json={"title": "Dos veces", "client_id": base_client.id})
    entry = await journal.only()

    assert (await admin_client.post(f"/api/changes/{entry.id}/undo")).status_code == 200
    repeat = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert repeat.status_code == 409


async def test_no_se_puede_deshacer_el_cambio_de_otra_persona(
    admin_client, member_client, base_client, journal
):
    await admin_client.post("/api/tasks", json={"title": "Mía", "client_id": base_client.id})
    entry = await journal.only()

    resp = await member_client.post(f"/api/changes/{entry.id}/undo")
    assert resp.status_code == 403


async def test_recent_solo_devuelve_los_mios_y_como_mucho_cinco(
    admin_client, member_client, base_client, journal
):
    for i in range(7):
        await admin_client.post("/api/tasks", json={
            "title": f"Tarea {i}", "client_id": base_client.id,
        })
    await journal.entries()

    mine = (await admin_client.get("/api/changes/recent")).json()
    assert len(mine) == 5
    assert mine[0]["label"] == "Tarea «Tarea 6» creada"   # el más reciente primero

    assert (await member_client.get("/api/changes/recent")).json() == []


async def test_lo_deshecho_desaparece_del_listado(admin_client, base_client, journal):
    await admin_client.post("/api/tasks", json={"title": "Fugaz", "client_id": base_client.id})
    entry = await journal.only()

    assert len((await admin_client.get("/api/changes/recent")).json()) == 1
    await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert (await admin_client.get("/api/changes/recent")).json() == []


# Savepoints are provisional: only the outer session commit is journalable.
async def test_savepoint_commit_then_outer_rollback_emits_nothing(db_session, journal):
    cj.set_actor(journal.actor_id)
    async with db_session.begin_nested():
        db_session.add(Task(title="Rolled back outside", status=TaskStatus.pending))
        await db_session.flush()
    assert (await journal.peek()) == []
    await db_session.rollback()
    assert (await journal.peek()) == []


async def test_savepoint_rollback_preserves_outer_operations(db_session, journal):
    cj.set_actor(journal.actor_id)
    outer = Task(title="Kept", status=TaskStatus.pending)
    db_session.add(outer)
    await db_session.flush()
    nested = await db_session.begin_nested()
    db_session.add(Task(title="Discarded", status=TaskStatus.pending))
    await db_session.flush()
    await nested.rollback()
    assert (await journal.peek()) == []
    await db_session.commit()
    assert len((await journal.peek())) == 1
    assert [op["after"]["title"] for op in (await journal.peek())[0]["operations"]] == ["Kept"]


async def test_deep_savepoint_rollback_discards_committed_descendants(db_session, journal):
    cj.set_actor(journal.actor_id)
    db_session.add(Task(title="Outer", status=TaskStatus.pending))
    await db_session.flush()
    nested = await db_session.begin_nested()
    db_session.add(Task(title="Child", status=TaskStatus.pending))
    await db_session.flush()
    async with db_session.begin_nested():
        db_session.add(Task(title="Grandchild", status=TaskStatus.pending))
        await db_session.flush()
    await nested.rollback()
    await db_session.commit()
    assert len((await journal.peek())) == 1
    assert [op["after"]["title"] for op in (await journal.peek())[0]["operations"]] == ["Outer"]


async def test_successful_savepoints_collapse_into_one_outer_entry(db_session, journal):
    cj.set_actor(journal.actor_id)
    task = Task(title="A", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.flush()
    for title in ["B", "C"]:
        async with db_session.begin_nested():
            task.title = title
            await db_session.flush()
        assert (await journal.peek()) == []
    await db_session.commit()
    assert len((await journal.peek())) == 1
    assert len((await journal.peek())[0]["operations"]) == 1
    assert (await journal.peek())[0]["operations"][0]["after"]["title"] == "C"


async def test_failed_flush_savepoint_preserves_outer_journal(db_session, journal):
    from sqlalchemy.exc import IntegrityError
    cj.set_actor(journal.actor_id)
    db_session.add(Task(title="Valid", status=TaskStatus.pending))
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(Task(title="Invalid", client_id=987654321, status=TaskStatus.pending))
            await db_session.flush()
    await db_session.commit()
    assert len((await journal.peek())) == 1
    assert [op["after"]["title"] for op in (await journal.peek())[0]["operations"]] == ["Valid"]


async def test_bulk_status_update_is_one_undo_action(admin_client, db_session, base_client, journal):
    first = await _make_task(db_session, base_client, title="First")
    second = await _make_task(db_session, base_client, title="Second")
    await db_session.commit()
    response = await admin_client.patch("/api/tasks/bulk/update", json={
        "ids": [first.id, second.id], "updates": {"status": "completed"},
    })
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2
    entry = await journal.only()
    assert {op["entity_id"] for op in entry.operations} == {first.id, second.id}
    undone = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert undone.status_code == 200, undone.text
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.status == second.status == TaskStatus.pending
    assert first.completed_at is second.completed_at is None


async def test_nested_rollback_restores_manual_time_capture_flag(db_session, journal):
    cj.set_actor(journal.actor_id)
    nested = await db_session.begin_nested()
    cj.capture_manual_time(db_session.sync_session)
    await nested.rollback()
    assert not db_session.info.get(cj._MANUAL_TIME_KEY)
    cj.capture_manual_time(db_session.sync_session)
    nested = await db_session.begin_nested()
    await nested.rollback()
    assert db_session.info.get(cj._MANUAL_TIME_KEY) is True
    await db_session.rollback()
    assert not db_session.info.get(cj._MANUAL_TIME_KEY)


async def test_journal_matches_committed_database_across_independent_sessions(engine, journal):
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import delete
    from backend.db.models import User, ChangeLog
    from uuid import uuid4
    task_id = None
    user_id = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as writer:
            actor = User(email=f"journal-{uuid4()}@test.local", full_name="Journal", hashed_password="unused")
            writer.add(actor)
            await writer.commit()
            user_id = actor.id
            task = Task(title="Original", status=TaskStatus.pending)
            writer.add(task)
            await writer.commit()
            task_id = task.id
            cj.set_actor(user_id)
            async with writer.begin_nested():
                task.title = "Provisional"
                await writer.flush()
            assert (await journal.peek()) == []
            await writer.rollback()
            async with AsyncSession(engine) as reader:
                assert await reader.scalar(select(Task.title).where(Task.id == task_id)) == "Original"
            await writer.refresh(task)
            async with writer.begin_nested():
                task.title = "Committed"
                await writer.flush()
            await writer.commit()
            assert len((await journal.peek())) == 1
            async with AsyncSession(engine) as reader:
                assert await reader.scalar(select(Task.title).where(Task.id == task_id)) == "Committed"
    finally:
        cj.set_actor(None)
        if task_id is not None:
            async with AsyncSession(engine) as cleanup:
                await cleanup.execute(delete(ChangeLog).where(ChangeLog.user_id == user_id))
                await cleanup.execute(delete(Task).where(Task.id == task_id))
                await cleanup.execute(delete(User).where(User.id == user_id))
                await cleanup.commit()


async def test_closing_session_discards_pending_journal_before_reuse(engine, journal):
    from sqlalchemy.ext.asyncio import AsyncSession
    writer = AsyncSession(engine)
    try:
        cj.set_actor(journal.actor_id)
        writer.add(Task(title="Abandoned", status=TaskStatus.pending))
        await writer.flush()
        await writer.close()
        assert not writer.info.get(cj._INFO_KEY)
        assert not writer.info.get(cj._SAVEPOINTS_KEY)
        await writer.commit()
        assert (await journal.peek()) == []
    finally:
        await writer.close()


async def test_automation_batch_journals_only_successful_actions_once(admin_client, db_session, journal):
    from backend.api.routes.automations import execute_automations
    from backend.db.models import AutomationRule, AutomationLog
    rules = [
        AutomationRule(name="Good A", trigger="task_completed", action_type="create_task", action_config={"title": "A"}, is_active=True),
        AutomationRule(name="Invalid", trigger="task_completed", action_type="create_insight", action_config={"task_id": 987654321}, is_active=True),
        AutomationRule(name="Good B", trigger="task_completed", action_type="create_task", action_config={"title": "B"}, is_active=True),
    ]
    db_session.add_all(rules)
    await db_session.commit()
    cj.set_actor(admin_client.test_user.id)
    await execute_automations("task_completed", {}, db_session)
    entry = await journal.only()
    assert len(entry.operations) == 2
    assert {op["after"]["title"] for op in entry.operations} == {"A", "B"}
    failed = (await db_session.execute(select(AutomationLog).where(AutomationLog.rule_id == rules[1].id))).scalar_one()
    assert failed.success is False
    response = await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert response.status_code == 200, response.text
    for op in entry.operations:
        assert await db_session.get(Task, op["entity_id"]) is None


async def test_journal_write_failure_rolls_back_domain_change(db_session, admin_user, journal):
    from sqlalchemy import event
    from backend.db.models import ChangeLog
    await db_session.commit()
    cj.set_actor(admin_user.id)
    task = Task(title="Must not survive journal failure", status=TaskStatus.pending)
    db_session.add(task)

    def reject_insert(mapper, connection, target):
        raise RuntimeError("simulated journal storage failure")

    event.listen(ChangeLog, "before_insert", reject_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated journal storage failure"):
            await db_session.commit()
    finally:
        event.remove(ChangeLog, "before_insert", reject_insert)
    task_id = task.id
    await db_session.rollback()
    assert await db_session.get(Task, task_id) is None
    assert await journal.peek() == []


async def test_prepared_receipt_id_is_stable_and_rollback_is_atomic(db_session, admin_user, journal):
    from backend.db.models import ChangeLog
    await db_session.commit()
    cj.set_actor(admin_user.id)
    task = Task(title="Receipt before commit", status=TaskStatus.pending)
    db_session.add(task)
    row = await db_session.run_sync(cj.prepare_entry)
    assert row.id is not None
    task.title = "Last edit before commit"
    again = await db_session.run_sync(cj.prepare_entry)
    assert again.id == row.id
    assert again.operations[0]["after"]["title"] == task.title
    row_id, task_id = row.id, task.id
    await db_session.rollback()
    assert await db_session.get(Task, task_id) is None
    assert await db_session.get(ChangeLog, row_id) is None
    assert not db_session.info.get(cj._ENTRY_KEY)


async def test_preparing_then_savepoint_rollback_keeps_original_snapshot(db_session, admin_user, journal):
    cj.set_actor(admin_user.id)
    task = Task(title="Keep outer", status=TaskStatus.pending)
    db_session.add(task)
    row = await db_session.run_sync(cj.prepare_entry)
    row_id = row.id
    nested = await db_session.begin_nested()
    task.title = "Discard inner"
    await db_session.flush()
    await nested.rollback()
    await db_session.commit()
    entry = await journal.only()
    assert entry.id == row_id
    assert entry.operations[0]["after"]["title"] == "Keep outer"


async def test_actor_is_bound_to_the_change_not_commit_context(db_session, admin_user, journal):
    cj.set_actor(admin_user.id)
    db_session.add(Task(title="Actor retained", status=TaskStatus.pending))
    await db_session.flush()
    cj.set_actor(None)
    await db_session.commit()
    entry = await journal.only()
    assert entry.user_id == admin_user.id


async def test_prepared_receipt_captures_later_edits_after_context_clear(db_session, admin_user, journal):
    cj.set_actor(admin_user.id)
    task = Task(title="Initial", status=TaskStatus.pending)
    db_session.add(task)
    provisional = await db_session.run_sync(cj.prepare_entry)
    cj.set_actor(None)
    task.title = "Final after clearing request context"
    await db_session.commit()
    entry = await journal.only()
    assert entry.id == provisional.id
    assert entry.user_id == admin_user.id
    assert entry.operations[0]["after"]["title"] == task.title


async def test_mixed_actors_cannot_confirm_one_transaction(db_session, admin_user, member_user, journal):
    cj.set_actor(admin_user.id)
    task = Task(title="First actor", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.run_sync(cj.prepare_entry)
    cj.set_actor(member_user.id)
    task.title = "Second actor"
    with pytest.raises(RuntimeError, match="mezclar autores"):
        await db_session.commit()
    task_id = task.id
    await db_session.rollback()
    cj.set_actor(None)
    assert await db_session.get(Task, task_id) is None
    assert await journal.peek() == []


async def test_journal_timestamp_is_utc_even_with_non_utc_database_session(db_session, admin_client, journal):
    from sqlalchemy import text
    from backend.services.temporal import utc_now_naive
    await db_session.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
    before = utc_now_naive()
    response = await admin_client.post("/api/tasks", json={"title": "UTC journal receipt"})
    assert response.status_code == 201, response.text
    entry = await journal.only()
    assert before <= entry.created_at <= utc_now_naive()
    recent = await admin_client.get("/api/changes/recent")
    row = next(row for row in recent.json() if row["id"] == entry.id)
    assert row["created_at"].endswith("Z")

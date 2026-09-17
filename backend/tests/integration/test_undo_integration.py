"""Undo end-to-end contra Postgres real.

La suite unitaria mockea ``get_db``, así que allí no se ejecuta SQL y los
eventos ORM del journal no llegan a dispararse: la captura sólo se puede
demostrar aquí. Se cubre el ciclo completo — hacer el cambio por HTTP, ver la
entrada del journal, deshacerla y comprobar el estado de la fila.

La escritura de la entrada es fire-and-forget en producción (una tarea suelta
con su propia sesión). Aquí se sustituye ``_sink`` para persistirla en la misma
transacción del test; lo que se prueba es el CONTENIDO que produce la captura,
que es lo que luego sabe deshacer la ruta.
"""
from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.db.models import (
    Client,
    ClientStatus,
    Project,
    Task,
    TaskChecklist,
    TaskPriority,
    TaskStatus,
    TimeEntry,
)
from backend.services import change_journal as cj

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def journal(db_session, monkeypatch):
    """Recoge lo que el journal registraría y lo persiste bajo demanda."""
    captured: list[dict] = []
    cj.set_actor(None)
    monkeypatch.setattr(cj, "_sink", captured.append)

    class _Journal:
        raw = captured

        async def entries(self):
            """Vuelca lo capturado a ``change_logs`` y devuelve las filas."""
            from backend.db.models import ChangeLog

            rows = [ChangeLog(**entry) for entry in captured]
            captured.clear()
            for row in rows:
                db_session.add(row)
            await db_session.commit()
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

    assert journal.raw == []


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


async def test_deshacer_no_se_registra_como_cambio_nuevo(
    admin_client, base_client, journal
):
    """Si el undo se registrara, el historial sería un bucle deshacer/rehacer."""
    await admin_client.post("/api/tasks", json={"title": "Una", "client_id": base_client.id})
    entry = await journal.only()

    await admin_client.post(f"/api/changes/{entry.id}/undo")
    assert journal.raw == []


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
    cj.set_actor(1)
    async with db_session.begin_nested():
        db_session.add(Task(title="Rolled back outside", status=TaskStatus.pending))
        await db_session.flush()
    assert journal.raw == []
    await db_session.rollback()
    assert journal.raw == []


async def test_savepoint_rollback_preserves_outer_operations(db_session, journal):
    cj.set_actor(1)
    outer = Task(title="Kept", status=TaskStatus.pending)
    db_session.add(outer)
    await db_session.flush()
    nested = await db_session.begin_nested()
    db_session.add(Task(title="Discarded", status=TaskStatus.pending))
    await db_session.flush()
    await nested.rollback()
    assert journal.raw == []
    await db_session.commit()
    assert len(journal.raw) == 1
    assert [op["after"]["title"] for op in journal.raw[0]["operations"]] == ["Kept"]


async def test_deep_savepoint_rollback_discards_committed_descendants(db_session, journal):
    cj.set_actor(1)
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
    assert len(journal.raw) == 1
    assert [op["after"]["title"] for op in journal.raw[0]["operations"]] == ["Outer"]


async def test_successful_savepoints_collapse_into_one_outer_entry(db_session, journal):
    cj.set_actor(1)
    task = Task(title="A", status=TaskStatus.pending)
    db_session.add(task)
    await db_session.flush()
    for title in ["B", "C"]:
        async with db_session.begin_nested():
            task.title = title
            await db_session.flush()
        assert journal.raw == []
    await db_session.commit()
    assert len(journal.raw) == 1
    assert len(journal.raw[0]["operations"]) == 1
    assert journal.raw[0]["operations"][0]["after"]["title"] == "C"


async def test_failed_flush_savepoint_preserves_outer_journal(db_session, journal):
    from sqlalchemy.exc import IntegrityError
    cj.set_actor(1)
    db_session.add(Task(title="Valid", status=TaskStatus.pending))
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(Task(title="Invalid", client_id=987654321, status=TaskStatus.pending))
            await db_session.flush()
    await db_session.commit()
    assert len(journal.raw) == 1
    assert [op["after"]["title"] for op in journal.raw[0]["operations"]] == ["Valid"]


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
    cj.set_actor(1)
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
    task_id = None
    try:
        async with AsyncSession(engine, expire_on_commit=False) as writer:
            task = Task(title="Original", status=TaskStatus.pending)
            writer.add(task)
            await writer.commit()
            task_id = task.id
            cj.set_actor(1)
            async with writer.begin_nested():
                task.title = "Provisional"
                await writer.flush()
            assert journal.raw == []
            await writer.rollback()
            async with AsyncSession(engine) as reader:
                assert await reader.scalar(select(Task.title).where(Task.id == task_id)) == "Original"
            await writer.refresh(task)
            async with writer.begin_nested():
                task.title = "Committed"
                await writer.flush()
            await writer.commit()
            assert len(journal.raw) == 1
            async with AsyncSession(engine) as reader:
                assert await reader.scalar(select(Task.title).where(Task.id == task_id)) == "Committed"
    finally:
        cj.set_actor(None)
        if task_id is not None:
            async with AsyncSession(engine) as cleanup:
                await cleanup.execute(delete(Task).where(Task.id == task_id))
                await cleanup.commit()


async def test_closing_session_discards_pending_journal_before_reuse(engine, journal):
    from sqlalchemy.ext.asyncio import AsyncSession
    writer = AsyncSession(engine)
    try:
        cj.set_actor(1)
        writer.add(Task(title="Abandoned", status=TaskStatus.pending))
        await writer.flush()
        await writer.close()
        assert not writer.info.get(cj._INFO_KEY)
        assert not writer.info.get(cj._SAVEPOINTS_KEY)
        await writer.commit()
        assert journal.raw == []
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

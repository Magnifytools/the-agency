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

import pytest
import pytest_asyncio

from backend.db.models import (
    Client,
    ClientStatus,
    Project,
    Task,
    TaskChecklist,
    TaskPriority,
    TaskStatus,
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

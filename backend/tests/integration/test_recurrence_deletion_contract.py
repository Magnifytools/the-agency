"""Destructive scope operations preserve recurrence generation invariants."""
import asyncio
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.db.models import (
    Client,
    Project,
    ProjectStatus,
    Task,
    TaskRecurrenceOccurrence,
    TaskStatus,
)
from backend.services.recurrence import generate_recurring_instances

pytestmark = pytest.mark.integration


async def test_project_delete_pauses_template_before_unlinking(
    admin_client, db_session
):
    client = Client(name="Cliente proyecto borrado")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Proyecto recurrente borrado",
        client_id=client.id,
        status=ProjectStatus.active,
    )
    db_session.add(project)
    await db_session.flush()
    template = Task(
        title="Plantilla que no debe quedar huérfana activa",
        client_id=client.id,
        project_id=project.id,
        status=TaskStatus.pending,
        is_recurring=True,
        recurrence_pattern="monthly",
        recurrence_day=15,
    )
    db_session.add(template)
    await db_session.commit()

    response = await admin_client.delete(f"/api/projects/{project.id}")

    assert response.status_code == 204, response.text
    await db_session.refresh(template)
    assert template.project_id is None
    assert template.recurrence_paused_at is not None
    assert await generate_recurring_instances(db_session, target_date=date(2026, 9, 15)) == 0


async def test_project_delete_waits_for_recurrence_transaction(
    admin_client, db_session, engine
):
    client = Client(name="Cliente carrera borrado")
    db_session.add(client)
    await db_session.flush()
    project = Project(name="Proyecto carrera", client_id=client.id, status=ProjectStatus.active)
    db_session.add(project)
    await db_session.flush()
    template = Task(
        title="Plantilla carrera", client_id=client.id, project_id=project.id,
        status=TaskStatus.pending, is_recurring=True,
        recurrence_pattern="monthly", recurrence_day=15,
    )
    db_session.add(template)
    await db_session.commit()

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as worker:
        await worker.execute(text("SELECT pg_advisory_xact_lock(76241317)"))
        deleting = asyncio.create_task(admin_client.delete(f"/api/projects/{project.id}"))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(deleting), timeout=0.1)
        await worker.commit()
        response = await asyncio.wait_for(deleting, timeout=2)

    assert response.status_code == 204, response.text
    await db_session.refresh(template)
    assert template.project_id is None
    assert template.recurrence_paused_at is not None


async def test_hard_delete_client_erases_closed_recurrence_graph(
    admin_client, db_session
):
    client = Client(name="Cliente borrado irreversible")
    db_session.add(client)
    await db_session.flush()
    template = Task(
        title="Plantilla del cliente",
        client_id=client.id,
        status=TaskStatus.pending,
        is_recurring=True,
        recurrence_pattern="monthly",
        recurrence_day=15,
    )
    db_session.add(template)
    await db_session.flush()
    child = Task(
        title="Instancia del cliente",
        client_id=client.id,
        status=TaskStatus.pending,
        recurring_parent_id=template.id,
        recurrence_occurrence_date=date(2026, 9, 15),
    )
    db_session.add(child)
    await db_session.flush()
    db_session.add(TaskRecurrenceOccurrence(
        template_id=template.id,
        date=date(2026, 9, 15),
        task_id=child.id,
    ))
    await db_session.commit()
    client_id = client.id
    template_id = template.id
    child_id = child.id

    response = await admin_client.delete(f"/api/clients/{client_id}/hard")

    assert response.status_code == 204, response.text
    assert await db_session.scalar(select(func.count()).select_from(Client).where(
        Client.id == client_id
    )) == 0
    assert await db_session.scalar(select(func.count()).select_from(Task).where(
        Task.id.in_([template_id, child_id])
    )) == 0
    assert await db_session.scalar(select(func.count()).select_from(
        TaskRecurrenceOccurrence
    ).where(TaskRecurrenceOccurrence.template_id == template_id)) == 0


async def test_hard_delete_rejects_cross_client_recurrence_before_mutation(
    admin_client, db_session
):
    owner = Client(name="Cliente propietario de plantilla")
    other = Client(name="Cliente de instancia inconsistente")
    db_session.add_all([owner, other])
    await db_session.flush()
    template = Task(
        title="Plantilla cruzada",
        client_id=owner.id,
        status=TaskStatus.pending,
        is_recurring=True,
        recurrence_pattern="monthly",
        recurrence_day=15,
    )
    db_session.add(template)
    await db_session.flush()
    child = Task(
        title="Instancia de otro cliente",
        client_id=other.id,
        status=TaskStatus.pending,
        recurring_parent_id=template.id,
        recurrence_occurrence_date=date(2026, 9, 15),
    )
    db_session.add(child)
    await db_session.flush()
    receipt = TaskRecurrenceOccurrence(
        template_id=template.id,
        date=date(2026, 9, 15),
        task_id=child.id,
    )
    db_session.add(receipt)
    await db_session.commit()

    response = await admin_client.delete(f"/api/clients/{owner.id}/hard")

    assert response.status_code == 409, response.text
    assert "otro cliente" in response.json()["detail"]
    assert await db_session.get(Client, owner.id) is not None
    assert await db_session.get(Task, template.id) is not None
    assert await db_session.get(TaskRecurrenceOccurrence, receipt.id) is not None

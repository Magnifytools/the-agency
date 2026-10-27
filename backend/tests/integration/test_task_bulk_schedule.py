"""Planificar varias tareas a la vez desde la selección en bloque."""

from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.db.models import Client, ClientStatus, Task, TaskStatus


pytestmark = pytest.mark.integration


@pytest.fixture
async def two_tasks(db_session):
    client = Client(name=f"Bloque {uuid4().hex[:8]}", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    tasks = [
        Task(title="Uno", client_id=client.id, status=TaskStatus.pending),
        Task(title="Dos", client_id=client.id, status=TaskStatus.pending, scheduled_date=date(2026, 10, 20)),
    ]
    db_session.add_all(tasks)
    await db_session.flush()
    return [task.id for task in tasks]


async def _rows(db_session, ids):
    db_session.expire_all()
    rows = (await db_session.execute(select(Task).where(Task.id.in_(ids)).order_by(Task.id))).scalars().all()
    return rows


async def test_bulk_plans_every_selected_task_for_the_same_day(admin_client, db_session, two_tasks):
    response = await admin_client.patch("/api/tasks/bulk/update", json={
        "ids": two_tasks, "updates": {"scheduled_date": "2026-10-29"},
    })
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2
    assert [task.scheduled_date for task in await _rows(db_session, two_tasks)] == [date(2026, 10, 29)] * 2


async def test_bulk_unplans_with_null(admin_client, db_session, two_tasks):
    response = await admin_client.patch("/api/tasks/bulk/update", json={
        "ids": two_tasks, "updates": {"scheduled_date": None},
    })
    assert response.status_code == 200, response.text
    assert [task.scheduled_date for task in await _rows(db_session, two_tasks)] == [None, None]


async def test_bulk_due_date_text_is_stored_as_a_date(admin_client, db_session, two_tasks):
    response = await admin_client.patch("/api/tasks/bulk/update", json={
        "ids": two_tasks, "updates": {"due_date": "2026-11-03"},
    })
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 2
    assert [task.due_date for task in await _rows(db_session, two_tasks)] == [datetime(2026, 11, 3)] * 2


async def test_bulk_rejects_a_malformed_day_before_touching_anything(admin_client, db_session, two_tasks):
    response = await admin_client.patch("/api/tasks/bulk/update", json={
        "ids": two_tasks, "updates": {"scheduled_date": "29/10/2026"},
    })
    assert response.status_code == 422
    assert [task.scheduled_date for task in await _rows(db_session, two_tasks)] == [None, date(2026, 10, 20)]

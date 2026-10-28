"""Subtareas en Mi agenda: las que me tocan en tareas que lleva otra persona."""
from datetime import date, timedelta

import pytest

from backend.db.models import Task, TaskChecklist, TaskStatus, UserRole
from backend.tests.integration.conftest import _create_user

pytestmark = pytest.mark.integration

TODAY = date(2031, 3, 10)


async def test_my_subtasks_in_other_peoples_tasks_show_up_until_done(admin_client, db_session):
    me = admin_client.test_user
    other = await _create_user(db_session, email="otra-sub@test.com", full_name="Otra Persona", role=UserRole.member)
    theirs = Task(title="Informe de Nacho", assigned_to=other.id, created_by=other.id)
    mine = Task(title="Mi tarea", assigned_to=me.id, created_by=me.id)
    closed = Task(title="Ya cerrada", assigned_to=other.id, created_by=other.id, status=TaskStatus.completed)
    db_session.add_all([theirs, mine, closed])
    await db_session.flush()
    db_session.add_all([
        TaskChecklist(task_id=theirs.id, text="Revisar enlaces", assigned_to=me.id, due_date=TODAY),
        TaskChecklist(task_id=theirs.id, text="Sin fecha", assigned_to=me.id, order_index=1),
        TaskChecklist(task_id=theirs.id, text="Para la semana que viene", assigned_to=me.id, due_date=TODAY + timedelta(days=7)),
        TaskChecklist(task_id=theirs.id, text="Ya hecha", assigned_to=me.id, is_done=True),
        TaskChecklist(task_id=theirs.id, text="De otra persona", assigned_to=other.id),
        TaskChecklist(task_id=mine.id, text="De mi propia tarea", assigned_to=me.id),
        TaskChecklist(task_id=closed.id, text="De una cerrada", assigned_to=me.id),
    ])
    await db_session.commit()

    response = await admin_client.get("/api/tasks/agenda/subtasks", params={"date": TODAY.isoformat()})
    assert response.status_code == 200, response.text
    items = response.json()
    assert [item["text"] for item in items] == ["Revisar enlaces", "Sin fecha"]
    assert items[0]["task_title"] == "Informe de Nacho"
    assert items[0]["task_assignee_name"] == "Otra Persona"

    done = await admin_client.put(f"/api/tasks/{theirs.id}/checklist/{items[0]['id']}", json={"is_done": True})
    assert done.status_code == 200, done.text
    again = await admin_client.get("/api/tasks/agenda/subtasks", params={"date": TODAY.isoformat()})
    assert [item["text"] for item in again.json()] == ["Sin fecha"]


async def test_subtasks_need_the_tasks_module(member_client):
    response = await member_client.get("/api/tasks/agenda/subtasks", params={"date": TODAY.isoformat()})
    assert response.status_code == 403

"""Bloques de trabajo con hora de Mi agenda (/api/time-blocks)."""

from datetime import datetime

import pytest
from sqlalchemy import select

from backend.db.models import Client, Task, TaskStatus, TaskTimeBlock

pytestmark = pytest.mark.integration


async def _task(db_session, **fields):
    client = Client(name="Acme")
    db_session.add(client)
    await db_session.flush()
    task = Task(title=fields.pop("title", "Informe"), status=fields.pop("status", TaskStatus.pending),
                client_id=client.id, estimated_minutes=90, **fields)
    db_session.add(task)
    await db_session.flush()
    return task


async def test_create_list_move_and_delete_my_blocks(admin_client, db_session):
    task = await _task(db_session)
    created = await admin_client.post("/api/time-blocks", json={
        "task_id": task.id, "starts_at": "2026-10-28T10:00", "ends_at": "2026-10-28T11:30",
    })
    assert created.status_code == 201, created.text
    block = created.json()
    assert (block["task_title"], block["client_name"], block["task_estimated_minutes"]) == ("Informe", "Acme", 90)

    listed = await admin_client.get("/api/time-blocks", params={"date_from": "2026-10-26", "date_to": "2026-10-30"})
    assert [item["id"] for item in listed.json()] == [block["id"]]
    assert (await admin_client.get("/api/time-blocks", params={"date_from": "2026-10-29", "date_to": "2026-10-30"})).json() == []

    moved = await admin_client.patch(f"/api/time-blocks/{block['id']}", json={"starts_at": "2026-10-29T16:00", "ends_at": "2026-10-29T17:30"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["starts_at"].startswith("2026-10-29T16:00")

    assert (await admin_client.delete(f"/api/time-blocks/{block['id']}")).status_code == 204
    # Borrar el bloque no toca la tarea.
    assert (await db_session.execute(select(Task.id).where(Task.id == task.id))).scalar_one() == task.id


@pytest.mark.parametrize(("starts_at", "ends_at"), [
    ("2026-10-28T11:00", "2026-10-28T10:00"),
    ("2026-10-28T23:00", "2026-10-29T01:00"),
    ("2026-10-28T06:00", "2026-10-28T19:00"),
    ("2026-10-28T10:00+01:00", "2026-10-28T11:00+01:00"),
])
async def test_rejects_impossible_blocks(admin_client, db_session, starts_at, ends_at):
    task = await _task(db_session)
    response = await admin_client.post("/api/time-blocks", json={"task_id": task.id, "starts_at": starts_at, "ends_at": ends_at})
    assert response.status_code == 422


async def test_a_block_may_end_at_midnight(admin_client, db_session):
    task = await _task(db_session)
    response = await admin_client.post("/api/time-blocks", json={"task_id": task.id, "starts_at": "2026-10-28T23:00", "ends_at": "2026-10-29T00:00"})
    assert response.status_code == 201, response.text


async def test_only_plannable_tasks_and_only_my_blocks(admin_client, make_member_client, db_session):
    done = await _task(db_session, status=TaskStatus.completed)
    template = await _task(db_session, is_recurring=True, recurrence_pattern="weekly", recurrence_day=1)
    for task in (done, template):
        response = await admin_client.post("/api/time-blocks", json={"task_id": task.id, "starts_at": "2026-10-28T10:00", "ends_at": "2026-10-28T11:00"})
        assert response.status_code == 422

    task = await _task(db_session)
    mine = (await admin_client.post("/api/time-blocks", json={"task_id": task.id, "starts_at": "2026-10-28T10:00", "ends_at": "2026-10-28T11:00"})).json()
    other = await make_member_client([("tasks", True, True)])
    assert (await other.get("/api/time-blocks", params={"date_from": "2026-10-28", "date_to": "2026-10-28"})).json() == []
    assert (await other.delete(f"/api/time-blocks/{mine['id']}")).status_code == 404
    reader = await make_member_client([("tasks", True, False)])
    assert (await reader.post("/api/time-blocks", json={"task_id": task.id, "starts_at": "2026-10-28T12:00", "ends_at": "2026-10-28T13:00"})).status_code == 403
    assert (await admin_client.get("/api/time-blocks", params={"date_from": "2026-10-01", "date_to": "2026-10-28"})).status_code == 422
    await other.aclose()
    await reader.aclose()


async def test_deleting_a_block_is_undoable_and_deleting_the_task_takes_its_blocks(admin_client, db_session):
    task = await _task(db_session)
    block = (await admin_client.post("/api/time-blocks", json={"task_id": task.id, "starts_at": "2026-10-28T10:00", "ends_at": "2026-10-28T11:00"})).json()
    await admin_client.delete(f"/api/time-blocks/{block['id']}")
    recent = (await admin_client.get("/api/changes/recent")).json()
    assert recent[0]["label"] == "Bloque «28/10 10:00–11:00» eliminado"
    assert (await admin_client.post(f"/api/changes/{recent[0]['id']}/undo")).status_code == 200
    restored = (await db_session.execute(select(TaskTimeBlock).where(TaskTimeBlock.id == block["id"]).execution_options(populate_existing=True))).scalar_one()
    assert restored.starts_at == datetime(2026, 10, 28, 10, 0)

    assert (await admin_client.delete(f"/api/tasks/{task.id}")).status_code == 204
    assert (await db_session.execute(select(TaskTimeBlock.id).where(TaskTimeBlock.task_id == task.id))).all() == []


async def test_time_blocks_migration_is_the_last_one():
    from backend.startup import deployment_schema
    from backend.startup.task_time_blocks_schema import MIGRATION

    assert MIGRATION in deployment_schema.MIGRATIONS


async def test_calendar_events_of_a_week_for_the_hours_view(admin_client, db_session):
    from backend.db.models import Event, EventType

    me = admin_client.test_user.id
    db_session.add_all([
        Event(user_id=me, title="Llamada Acme", event_type=EventType.meeting, source="google",
              start_time=datetime(2026, 10, 28, 9, 30), end_time=datetime(2026, 10, 28, 10, 0)),
        Event(user_id=me, title="Fuera de la semana", event_type=EventType.meeting,
              start_time=datetime(2026, 11, 3, 9, 30)),
    ])
    await db_session.flush()
    response = await admin_client.get("/api/calendar/events", params={"date_from": "2026-10-26", "date_to": "2026-10-30"})
    assert response.status_code == 200, response.text
    assert [(item["title"], item["start_time"][:16], item["end_time"][:16]) for item in response.json()] == [
        ("Llamada Acme", "2026-10-28T09:30", "2026-10-28T10:00"),
    ]

"""Arrastrar tareas: orden manual (sort_rank), estado y día en una sola acción."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.db.models import Client, Project, Task, TaskStatus
from backend.services.temporal import business_today

pytestmark = pytest.mark.integration


async def _tasks(db_session, count, **fields):
    tasks = [Task(title=f"T{index}", status=fields.pop("status", TaskStatus.pending), **fields) for index in range(count)]
    db_session.add_all(tasks)
    await db_session.flush()
    return [task.id for task in tasks]


async def _ranks(db_session, ids):
    rows = (await db_session.execute(
        select(Task.id, Task.sort_rank).where(Task.id.in_(ids)).execution_options(populate_existing=True)
    )).all()
    return {row.id: row.sort_rank for row in rows}


async def test_first_move_orders_the_whole_list_then_only_the_moved_task(admin_client, db_session):
    a, b, c = await _tasks(db_session, 3)
    first = await admin_client.post(f"/api/tasks/{c}/move", json={"ordered_ids": [c, a, b]})
    assert first.status_code == 200, first.text
    assert first.json()["ranks"] == {str(c): "F", str(a): "V", str(b): "k"}
    assert first.json()["task"]["sort_rank"] == "F"

    second = await admin_client.post(f"/api/tasks/{b}/move", json={"ordered_ids": [c, b, a]})
    assert second.json()["ranks"] == {str(b): "N"}
    ranks = await _ranks(db_session, [a, b, c])
    assert sorted([a, b, c], key=lambda task_id: ranks[task_id]) == [c, b, a]


async def test_agenda_follows_the_manual_order(admin_client, db_session):
    today = business_today()
    me = admin_client.test_user.id
    a, b, c = await _tasks(db_session, 3, assigned_to=me, scheduled_date=today)
    await admin_client.post(f"/api/tasks/{a}/move", json={"ordered_ids": [b, c, a]})
    response = await admin_client.get("/api/tasks/agenda", params={"date": today.isoformat(), "section": "planned"})
    assert [item["id"] for item in response.json()["items"]] == [b, c, a]


async def test_drop_on_another_column_or_day_changes_it_in_the_same_action(admin_client, db_session):
    a, b = await _tasks(db_session, 2)
    tomorrow = business_today() + timedelta(days=1)
    moved = await admin_client.post(f"/api/tasks/{a}/move", json={
        "ordered_ids": [b, a], "status": "in_progress", "scheduled_date": tomorrow.isoformat(),
    })
    assert moved.status_code == 200, moved.text
    assert moved.json()["task"]["status"] == "in_progress"
    assert moved.json()["task"]["scheduled_date"] == tomorrow.isoformat()

    # Una sola entrada del Deshacer devuelve estado, día y orden.
    recent = (await admin_client.get("/api/changes/recent")).json()
    undo = await admin_client.post(f"/api/changes/{recent[0]['id']}/undo")
    assert undo.status_code == 200, undo.text
    task = (await db_session.execute(
        select(Task).where(Task.id == a).execution_options(populate_existing=True)
    )).scalar_one()
    assert (task.status, task.scheduled_date, task.sort_rank) == (TaskStatus.pending, None, None)
    assert (await _ranks(db_session, [b]))[b] is None


async def test_move_keeps_the_task_rules(admin_client, make_member_client, db_session):
    a, b = await _tasks(db_session, 2)
    waiting = await admin_client.post(f"/api/tasks/{a}/move", json={"ordered_ids": [a, b], "status": "waiting"})
    assert waiting.status_code == 422
    missing = await admin_client.post(f"/api/tasks/{a}/move", json={"ordered_ids": [a, b, 99999999]})
    assert missing.status_code == 409
    outside = await admin_client.post(f"/api/tasks/{a}/move", json={"ordered_ids": [b]})
    assert outside.status_code == 422

    member = await make_member_client([("tasks", True, True)])
    owner = admin_client.test_user
    project = Project(name="SEO", client=Client(name=f"Mover {uuid4().hex[:6]}"),
                      owner_id=owner.id, requires_task_review=True)
    db_session.add(project)
    await db_session.flush()
    (reviewed,) = await _tasks(db_session, 1, project_id=project.id, client_id=project.client_id)
    closed = await member.post(f"/api/tasks/{reviewed}/move", json={"ordered_ids": [reviewed], "status": "completed"})
    assert closed.status_code == 409
    assert (await _ranks(db_session, [reviewed]))[reviewed] is None

    reader = await make_member_client([("tasks", True, False)])
    assert (await reader.post(f"/api/tasks/{a}/move", json={"ordered_ids": [a, b]})).status_code == 403
    await member.aclose()
    await reader.aclose()


async def test_sort_rank_migration_is_registered():
    from backend.startup import deployment_schema
    from backend.startup.task_sort_rank_schema import MIGRATION

    assert MIGRATION in deployment_schema.MIGRATIONS
    assert deployment_schema.MIGRATIONS[-1] is MIGRATION

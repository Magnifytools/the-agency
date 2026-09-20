"""Undo respects durable retirement and work created after restoration."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.db.models import ChangeLog, Task, TaskStatus, TimeEntry
from backend.services.temporal import business_today

pytestmark = pytest.mark.asyncio


async def _task(db_session, **values):
    task = Task(title="Carryover undo", scheduled_date=business_today() - timedelta(days=2), **values)
    db_session.add(task)
    await db_session.commit()
    return task


async def _last_change(db_session, task_id):
    return (await db_session.scalars(select(ChangeLog).where(
        ChangeLog.entity_type == "task", ChangeLog.entity_id == task_id,
    ).order_by(ChangeLog.id.desc()).limit(1))).one()


async def _retire(client, task_id, reason="Ya no hace falta"):
    current = (await client.get(f"/api/tasks/{task_id}")).json()
    response = await client.post(f"/api/tasks/{task_id}/carryover-decision", json={
        "action": "retire", "reason": reason, "expected_updated_at": current["updated_at"],
    })
    assert response.status_code == 200, response.text
    return response.json()


async def _restore(client, task_id):
    current = (await client.get(f"/api/tasks/{task_id}")).json()
    response = await client.post(f"/api/tasks/{task_id}/restore", json={
        "expected_updated_at": current["updated_at"],
    })
    assert response.status_code == 200, response.text
    return response.json()


async def test_retirement_undo_preserves_later_annotation_and_hours(admin_client, db_session, admin_user):
    task = await _task(db_session, actual_minutes=37)
    db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=37))
    await db_session.commit()
    original = (await admin_client.get(f"/api/tasks/{task.id}")).json()
    await _retire(admin_client, task.id)
    retirement = await _last_change(db_session, task.id)
    assert (await admin_client.put(f"/api/tasks/{task.id}", json={"description": "Contexto histórico"})).status_code == 200
    result = await admin_client.post(f"/api/changes/{retirement.id}/undo")
    assert result.status_code == 200, result.text
    current = (await admin_client.get(f"/api/tasks/{task.id}")).json()
    assert current["retired_at"] is None and current["retired_reason"] is None
    assert current["description"] == "Contexto histórico"
    assert current["scheduled_date"] == original["scheduled_date"]
    assert current["status"] == original["status"]
    assert current["actual_minutes"] == 37


async def test_undo_restore_retires_atomically_again(admin_client, db_session):
    task = await _task(db_session)
    retired = await _retire(admin_client, task.id)
    await _restore(admin_client, task.id)
    restored = await _last_change(db_session, task.id)
    result = await admin_client.post(f"/api/changes/{restored.id}/undo")
    assert result.status_code == 200, result.text
    current = (await admin_client.get(f"/api/tasks/{task.id}")).json()
    assert current["retired_at"] == retired["retired_at"]
    assert current["retired_reason"] == retired["retired_reason"]


@pytest.mark.parametrize("later_work", ["timer", "dependent"])
async def test_undo_restore_revalidates_new_work(admin_client, db_session, admin_user, later_work):
    task = await _task(db_session)
    await _retire(admin_client, task.id)
    await _restore(admin_client, task.id)
    restored = await _last_change(db_session, task.id)
    if later_work == "timer":
        db_session.add(TimeEntry(task_id=task.id, user_id=admin_user.id, minutes=None))
    else:
        db_session.add(Task(title="Ahora depende de ella", depends_on=task.id))
    await db_session.commit()
    result = await admin_client.post(f"/api/changes/{restored.id}/undo")
    assert result.status_code == 409, result.text
    await db_session.refresh(task)
    current = (await admin_client.get(f"/api/tasks/{task.id}")).json()
    assert current["retired_at"] is None and current["retired_reason"] is None
    await db_session.refresh(restored)
    assert restored.undone_at is None


async def test_old_status_undo_cannot_modify_retired_work(admin_client, db_session):
    task = await _task(db_session)
    changed = await admin_client.put(f"/api/tasks/{task.id}", json={"status": "in_progress"})
    assert changed.status_code == 200, changed.text
    old = await _last_change(db_session, task.id)
    await _retire(admin_client, task.id)
    result = await admin_client.post(f"/api/changes/{old.id}/undo")
    assert result.status_code == 409, result.text
    await db_session.refresh(task)
    assert task.status == TaskStatus.in_progress and task.retired_at is not None


async def test_undo_retirement_cannot_restore_dependency_on_retired_source(admin_client, db_session):
    source = await _task(db_session)
    dependent = await _task(db_session, depends_on=source.id)
    await _retire(admin_client, dependent.id)
    retirement = await _last_change(db_session, dependent.id)
    await _retire(admin_client, source.id)
    result = await admin_client.post(f"/api/changes/{retirement.id}/undo")
    assert result.status_code == 409, result.text
    await db_session.refresh(dependent)
    await db_session.refresh(source)
    assert dependent.retired_at is not None and dependent.depends_on == source.id


async def test_previous_retirement_cannot_undo_a_new_retirement(admin_client, db_session):
    task = await _task(db_session)
    await _retire(admin_client, task.id)
    first = await _last_change(db_session, task.id)
    await _restore(admin_client, task.id)
    current = await _retire(admin_client, task.id, reason="Decisión posterior")
    result = await admin_client.post(f"/api/changes/{first.id}/undo")
    assert result.status_code == 409, result.text
    await db_session.refresh(task)
    after = (await admin_client.get(f"/api/tasks/{task.id}")).json()
    assert after["retired_reason"] == current["retired_reason"]
    assert after["retired_at"] == current["retired_at"]


async def test_manual_time_undo_remains_a_historical_correction(admin_client, db_session):
    task = await _task(db_session)
    response = await admin_client.put(f"/api/tasks/{task.id}", json={"actual_minutes": 45})
    assert response.status_code == 200, response.text
    adjustment = await _last_change(db_session, task.id)
    await _retire(admin_client, task.id)
    result = await admin_client.post(f"/api/changes/{adjustment.id}/undo")
    assert result.status_code == 200, result.text
    await db_session.refresh(task)
    assert task.actual_minutes is None and task.retired_at is not None
    assert not (await db_session.scalars(select(TimeEntry).where(TimeEntry.task_id == task.id))).all()


@pytest.mark.parametrize("operation", ["delete", "unlink", "complete"])
async def test_undo_revalidates_resulting_dependency(admin_client, db_session, operation):
    source = await _task(db_session)
    dependent = await _task(db_session, depends_on=source.id)
    dependent_id = dependent.id
    if operation == "delete":
        result = await admin_client.delete(f"/api/tasks/{dependent_id}")
        assert result.status_code == 204, result.text
    else:
        data = {"depends_on": None} if operation == "unlink" else {"status": "completed"}
        result = await admin_client.put(f"/api/tasks/{dependent_id}", json=data)
        assert result.status_code == 200, result.text
    change = await _last_change(db_session, dependent_id)
    await _retire(admin_client, source.id)
    result = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert result.status_code == 409, result.text
    await db_session.refresh(change)
    assert change.undone_at is None
    current = await admin_client.get(f"/api/tasks/{dependent_id}")
    if operation == "delete":
        assert current.status_code == 404
    elif operation == "unlink":
        assert current.json()["depends_on"] is None
    else:
        assert current.json()["status"] == "completed"


async def test_old_checklist_undo_cannot_change_retired_work(admin_client, db_session):
    task = await _task(db_session)
    item = await admin_client.post(f"/api/tasks/{task.id}/checklist", json={"text": "Paso pendiente"})
    assert item.status_code == 201, item.text
    change = (await db_session.scalars(select(ChangeLog).where(
        ChangeLog.entity_type == "task_checklist", ChangeLog.entity_id == item.json()["id"],
    ).order_by(ChangeLog.id.desc()).limit(1))).one()
    await _retire(admin_client, task.id)
    result = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert result.status_code == 409, result.text


async def test_legacy_create_undo_does_not_delete_later_retirement(admin_client, db_session):
    created = await admin_client.post("/api/tasks", json={
        "title": "Creada antes del retiro",
        "scheduled_date": (business_today() - timedelta(days=1)).isoformat(),
    })
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    change = await _last_change(db_session, task_id)
    # Journals written by P16 did not contain retirement columns.
    change.operations = [{**op, "after": {key: value for key, value in op["after"].items()
                                         if key not in {"retired_at", "retired_reason"}}}
                         for op in change.operations]
    await db_session.commit()
    await _retire(admin_client, task_id)
    result = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert result.status_code == 409, result.text
    assert (await admin_client.get(f"/api/tasks/{task_id}")).json()["retired_at"] is not None

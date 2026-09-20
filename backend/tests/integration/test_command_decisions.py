"""Command decision queries reuse the live incident authority without writes."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import event, insert

from backend.db.models import Notification, Task, TaskStatus, UserPermission
from backend.services.command_decisions import query_decisions

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 19, 10)  # noqa: DTZ001
DUE = datetime(2026, 9, 18, 9)  # noqa: DTZ001


async def add_permission(db, user_id: int):
    permission = UserPermission(
        user_id=user_id, module="tasks", can_read=True, can_write=False,
    )
    db.add(permission)
    await db.flush()
    return permission


async def add_incident(db, user_id: int, *, title: str, state: str = "active"):
    task = Task(
        title=title,
        assigned_to=user_id,
        status=TaskStatus.pending,
        due_date=DUE,
    )
    db.add(task)
    await db.flush()
    row = Notification(
        user_id=user_id,
        type="task_overdue",
        title=f"Tarea vencida: {title}",
        message="Compromiso vencido",
        link_url=f"/tasks?task={task.id}",
        entity_type="task",
        entity_id=task.id,
        entity_key=str(task.id),
        dedupe_key=f"task_overdue:task:{task.id}:{DUE.date().isoformat()}",
        incident_state=state,
        incident_severity="warning",
        incident_revision=1,
        incident_detected_at=NOW,
        incident_fingerprint="f" * 64,
        incident_snoozed_until=(NOW + timedelta(days=1)) if state == "snoozed" else None,
    )
    db.add(row)
    await db.flush()
    return task, row


async def test_mine_is_json_safe_ordered_and_read_only(db_session, admin_user):
    _, older = await add_incident(db_session, admin_user.id, title="Primera")
    _, newest = await add_incident(db_session, admin_user.id, title="Segunda")
    _, snoozed = await add_incident(
        db_session, admin_user.id, title="Pospuesta", state="snoozed"
    )
    before = (
        newest.incident_state,
        newest.incident_revision,
        newest.updated_at,
        snoozed.incident_state,
        snoozed.incident_snoozed_until,
    )

    result = await query_decisions(db_session, admin_user, page=1, page_size=1)

    assert result["kind"] == "decisions"
    assert result["total"] == 2
    assert result["has_more"] is True
    assert [item["id"] for item in result["items"]] == [newest.id]
    item = result["items"][0]
    assert item["type"] == "incident"
    assert item["label"] == item["title"]
    assert item["revision"] == 1
    assert item["recipient_name"] == admin_user.full_name
    assert item["created_at"] == "2026-09-19T10:00:00Z"
    json.dumps(result)
    assert before == (
        newest.incident_state,
        newest.incident_revision,
        newest.updated_at,
        snoozed.incident_state,
        snoozed.incident_snoozed_until,
    )
    assert older.id < newest.id < snoozed.id


async def test_team_requires_admin_and_rechecks_recipient_source_acl(
    db_session, admin_user, member_user
):
    permission = await add_permission(db_session, member_user.id)
    _, member_incident = await add_incident(
        db_session, member_user.id, title="Decisión del equipo"
    )

    visible = await query_decisions(db_session, admin_user, scope="team")
    assert [item["id"] for item in visible["items"]] == [member_incident.id]
    assert visible["items"][0]["recipient_id"] == member_user.id

    permission.can_read = False
    await db_session.flush()
    revoked = await query_decisions(db_session, admin_user, scope="team")
    assert revoked["total"] == 0

    with pytest.raises(HTTPException) as exc:
        await query_decisions(db_session, member_user, scope="team")
    assert exc.value.status_code == 403


async def test_pagination_total_is_after_acl_and_has_no_row_n_plus_one(
    db_session, admin_user, member_user, engine
):
    # This inaccessible source must not enter either total or page boundaries.
    await add_incident(db_session, member_user.id, title="Sin permiso")
    task_ids = list((await db_session.execute(
        insert(Task).returning(Task.id),
        [
            {
                "title": f"Volumen {index}",
                "assigned_to": admin_user.id,
                "status": TaskStatus.pending,
                "due_date": DUE,
                "is_recurring": False,
            }
            for index in range(1001)
        ],
    )).scalars())
    await db_session.execute(
        insert(Notification),
        [
            {
                "user_id": admin_user.id,
                "type": "task_overdue",
                "title": f"Tarea vencida: Volumen {index}",
                "message": "Compromiso vencido",
                "link_url": f"/tasks?task={task_id}",
                "entity_type": "task",
                "entity_id": task_id,
                "entity_key": str(task_id),
                "dedupe_key": f"task_overdue:task:{task_id}:{DUE.date().isoformat()}",
                "incident_state": "active",
                "incident_severity": "warning",
                "incident_revision": 1,
                "incident_detected_at": NOW,
                "incident_fingerprint": "a" * 64,
            }
            for index, task_id in enumerate(task_ids)
        ],
    )
    await db_session.flush()
    statements = 0

    def count(*_args):
        nonlocal statements
        statements += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        result = await query_decisions(
            db_session, admin_user, scope="team", page=11, page_size=100
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert statements == 2
    assert result["total"] == 1001
    assert len(result["items"]) == 1
    assert result["has_more"] is False


async def test_stale_source_is_excluded_without_reconciliation(db_session, admin_user):
    task, incident = await add_incident(db_session, admin_user.id, title="Ya terminada")
    task.status = TaskStatus.completed
    await db_session.flush()

    result = await query_decisions(db_session, admin_user)

    assert result["items"] == []
    assert incident.incident_state == "active"

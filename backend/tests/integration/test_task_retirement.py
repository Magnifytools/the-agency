"""PostgreSQL contracts for conscious carryover review and retirement."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, CommandReceipt, ChangeLog, Project, Task, TaskChecklist, TaskPriority, TaskStatus, TimeEntry, User, UserRole
from backend.services.commands import execute_or_prompt
from backend.services.domain_writes import create_task, update_task
from backend.services.task_retirement import lock_task_for_cas
from backend.services.temporal import business_today, utc_now_naive
from backend.api.routes.tasks import BulkUpdateBody, bulk_update_tasks

pytestmark = pytest.mark.asyncio


def _token(task: Task) -> str:
    return task.updated_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


async def _carryover(db, user_id: int, *, title="Arrastre", **kwargs) -> Task:
    task = Task(
        title=title, status=TaskStatus.pending, priority=TaskPriority.medium,
        assigned_to=user_id, created_by=user_id,
        scheduled_date=business_today() - timedelta(days=1), **kwargs,
    )
    db.add(task)
    await db.flush()
    return task


async def test_reschedule_and_wait_preserve_due_date(admin_client, db_session, admin_user):
    due = datetime.combine(business_today() - timedelta(days=2), datetime.min.time())
    task = await _carryover(db_session, admin_user.id, due_date=due)
    tomorrow = business_today() + timedelta(days=1)

    rescheduled = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "reschedule", "scheduled_date": tomorrow.isoformat(),
        "expected_updated_at": _token(task),
    })
    assert rescheduled.status_code == 200, rescheduled.text
    assert rescheduled.json()["scheduled_date"] == tomorrow.isoformat()
    assert rescheduled.json()["due_date"] == due.date().isoformat()

    waiting = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "wait", "waiting_for": "Respuesta del cliente",
        "follow_up_date": tomorrow.isoformat(),
        "expected_updated_at": rescheduled.json()["updated_at"],
    })
    assert waiting.status_code == 200, waiting.text
    body = waiting.json()
    assert body["status"] == "waiting" and body["scheduled_date"] is None
    assert body["due_date"] == due.date().isoformat()
    carryover = await admin_client.get("/api/tasks/agenda", params={
        "date": business_today().isoformat(), "section": "carryover", "assigned_to": "me",
    })
    assert [item["id"] for item in carryover.json()["items"]] == [task.id]


async def test_wait_without_deadline_leaves_carryover_and_unplanned(
    admin_client, db_session, admin_user,
):
    task = await _carryover(db_session, admin_user.id, title="Wait without deadline")
    response = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "wait", "waiting_for": "Aprobación",
        "follow_up_date": (business_today() + timedelta(days=2)).isoformat(),
        "expected_updated_at": _token(task),
    })
    assert response.status_code == 200, response.text
    for section in ("carryover", "unplanned"):
        page = await admin_client.get("/api/tasks/agenda", params={
            "date": business_today().isoformat(), "section": section, "assigned_to": "me",
        })
        assert page.status_code == 200
        assert task.id not in [item["id"] for item in page.json()["items"]]


async def test_retire_restore_is_durable_and_each_action_is_journaled(
    admin_client, db_session, admin_user,
):
    task = await _carryover(db_session, admin_user.id, title="Retirable")
    before = set(await db_session.scalars(select(ChangeLog.id)))
    retired = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "retire", "reason": "Ya no aporta valor",
        "expected_updated_at": _token(task),
    })
    assert retired.status_code == 200, retired.text
    assert retired.json()["retired_at"].endswith("Z")
    assert retired.json()["retired_reason"] == "Ya no aporta valor"
    assert (await admin_client.get("/api/tasks")).json()["total"] == 0
    history = await admin_client.get("/api/tasks", params={"retirement": "retired"})
    assert history.status_code == 200 and [row["id"] for row in history.json()["items"]] == [task.id]

    restored = await admin_client.post(f"/api/tasks/{task.id}/restore", json={
        "expected_updated_at": retired.json()["updated_at"],
    })
    assert restored.status_code == 200, restored.text
    assert restored.json()["retired_at"] is None and restored.json()["retired_reason"] is None
    assert restored.json()["scheduled_date"] == (business_today() - timedelta(days=1)).isoformat()
    rows = list(await db_session.scalars(
        select(ChangeLog).where(ChangeLog.id.notin_(before)).order_by(ChangeLog.id)
    ))
    assert len(rows) == 2
    assert all(row.action == "update" for row in rows)
    assert {key for row in rows for op in row.operations for key in op.get("after", {})} >= {
        "retired_at", "retired_reason",
    }


async def test_retire_restore_response_reloads_relationships_after_lock(
    admin_client, db_session, admin_user,
):
    client = Client(name="Cliente respuesta retiro")
    db_session.add(client)
    await db_session.flush()
    project = Project(
        name="Proyecto respuesta retiro", client_id=client.id,
    )
    db_session.add(project)
    await db_session.flush()
    task = await _carryover(
        db_session, admin_user.id, title="Respuesta con relaciones",
        client_id=client.id, project_id=project.id,
    )
    db_session.add(TaskChecklist(task_id=task.id, text="Paso visible", order_index=0))
    await db_session.flush()

    retired = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "retire", "reason": "Retiro comprobable",
        "expected_updated_at": _token(task),
    })
    assert retired.status_code == 200, retired.text
    assert retired.json()["client_name"] == client.name
    assert retired.json()["project_name"] == project.name
    assert retired.json()["checklist_count"] == 1

    restored = await admin_client.post(f"/api/tasks/{task.id}/restore", json={
        "expected_updated_at": retired.json()["updated_at"],
    })
    assert restored.status_code == 200, restored.text
    assert restored.json()["client_name"] == client.name
    assert restored.json()["project_name"] == project.name
    assert restored.json()["checklist_count"] == 1

    detail = await admin_client.get(f"/api/tasks/{task.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["client_name"] == client.name
    assert detail.json()["project_name"] == project.name
    assert detail.json()["checklist_count"] == 1


async def test_stale_token_accepts_equivalent_offsets_and_rejects_old_revision(
    admin_client, db_session, admin_user,
):
    task = await _carryover(db_session, admin_user.id)
    aware = task.updated_at.replace(tzinfo=timezone.utc)
    equivalent = aware.astimezone(timezone(timedelta(hours=2))).isoformat()
    rescheduled = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "reschedule",
        "scheduled_date": (business_today() - timedelta(days=2)).isoformat(),
        "expected_updated_at": equivalent,
    })
    assert rescheduled.status_code == 200, rescheduled.text
    # The integration harness wraps route commits in one outer transaction, so
    # PostgreSQL now() is intentionally stable. Advance the physical revision
    # with the DB clock to exercise the stale-token branch itself.
    await db_session.execute(update(Task).where(Task.id == task.id).values(
        updated_at=func.clock_timestamp(),
    ))
    await db_session.flush()
    stale = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "complete", "expected_updated_at": equivalent,
    })
    assert stale.status_code == 409
    assert "cambió" in stale.json()["detail"]


async def test_retirement_blocks_timer_new_time_checklist_and_operational_patch(
    admin_client, db_session, admin_user,
):
    task = await _carryover(db_session, admin_user.id)
    retired = await admin_client.post(f"/api/tasks/{task.id}/carryover-decision", json={
        "action": "retire", "reason": "Retirada consciente",
        "expected_updated_at": _token(task),
    })
    assert retired.status_code == 200
    assert (await admin_client.post("/api/timer/start", json={"task_id": task.id})).status_code == 409
    assert (await admin_client.post("/api/time-entries", json={"task_id": task.id, "minutes": 15})).status_code == 409
    assert (await admin_client.post(f"/api/tasks/{task.id}/checklist", json={"text": "Nuevo trabajo"})).status_code == 409
    assert (await admin_client.put(f"/api/tasks/{task.id}", json={"status": "in_progress"})).status_code == 409
    annotation = await admin_client.put(f"/api/tasks/{task.id}", json={"description": "Nota histórica corregida"})
    assert annotation.status_code == 200, annotation.text


async def test_active_timer_and_active_dependent_prevent_retirement(
    admin_client, db_session, admin_user,
):
    target = await _carryover(db_session, admin_user.id, title="Objetivo")
    timer = TimeEntry(user_id=admin_user.id, task_id=target.id, started_at=utc_now_naive(), date=utc_now_naive())
    db_session.add(timer)
    await db_session.flush()
    blocked_timer = await admin_client.post(f"/api/tasks/{target.id}/carryover-decision", json={
        "action": "retire", "reason": "No continuar", "expected_updated_at": _token(target),
    })
    assert blocked_timer.status_code == 409
    await db_session.delete(timer)
    await db_session.flush()
    dependent = Task(title="Dependiente", status=TaskStatus.pending, priority=TaskPriority.medium,
                     depends_on=target.id, assigned_to=admin_user.id, created_by=admin_user.id)
    db_session.add(dependent)
    await db_session.flush()
    blocked_dependency = await admin_client.post(f"/api/tasks/{target.id}/carryover-decision", json={
        "action": "retire", "reason": "No continuar", "expected_updated_at": _token(target),
    })
    assert blocked_dependency.status_code == 409

    dependent.status = TaskStatus.completed
    dependent.completed_at = utc_now_naive()
    await db_session.flush()
    allowed = await admin_client.post(f"/api/tasks/{target.id}/carryover-decision", json={
        "action": "retire", "reason": "Dependencia ya terminada",
        "expected_updated_at": _token(target),
    })
    assert allowed.status_code == 200, allowed.text


async def test_new_dependency_rejects_retired_target_and_closed_time_correction_survives(
    admin_client, db_session, admin_user,
):
    target = await _carryover(db_session, admin_user.id)
    entry = TimeEntry(user_id=admin_user.id, task_id=target.id, minutes=10,
                      date=utc_now_naive(), notes="Trabajo histórico")
    db_session.add(entry)
    await db_session.flush()
    retired = await admin_client.post(f"/api/tasks/{target.id}/carryover-decision", json={
        "action": "retire", "reason": "Fin", "expected_updated_at": _token(target),
    })
    assert retired.status_code == 200
    rejected = await admin_client.post("/api/tasks", json={"title": "Nueva", "depends_on": target.id})
    assert rejected.status_code == 409
    corrected = await admin_client.put(f"/api/time-entries/{entry.id}", json={"minutes": 20})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["minutes"] == 20


async def test_prepared_log_time_receipt_revalidates_retirement_in_shared_writer(
    db_session, admin_user,
):
    task = await _carryover(db_session, admin_user.id, title="Command hours")
    receipt = CommandReceipt(
        id="retirement-command-receipt", user_id=admin_user.id,
        request_key="retirement-command-key", request_hash="hash", channel="app",
        raw_text="Registra 15 minutos", status="needs_review", revision=1,
        intent={"kind": "log_time", "task_id": task.id, "minutes": 15,
                "entry_date": business_today().isoformat()},
    )
    db_session.add(receipt)
    await db_session.flush()
    task.retired_at, task.retired_reason = utc_now_naive(), "Retirada tras preparar"
    await db_session.flush()
    with pytest.raises(Exception) as exc:
        await execute_or_prompt(db_session, receipt, admin_user, reviewed=True)
    assert getattr(exc.value, "status_code", None) == 409
    assert await db_session.scalar(select(TimeEntry.id).where(TimeEntry.task_id == task.id)) is None


async def test_restore_rejects_a_dependency_that_was_retired_while_child_inactive(
    admin_client, db_session, admin_user,
):
    parent = await _carryover(db_session, admin_user.id, title="Parent")
    child = await _carryover(db_session, admin_user.id, title="Child", depends_on=parent.id)
    child_retired = await admin_client.post(f"/api/tasks/{child.id}/carryover-decision", json={
        "action": "retire", "reason": "Child fuera", "expected_updated_at": _token(child),
    })
    assert child_retired.status_code == 200, child_retired.text
    parent_retired = await admin_client.post(f"/api/tasks/{parent.id}/carryover-decision", json={
        "action": "retire", "reason": "Parent fuera", "expected_updated_at": _token(parent),
    })
    assert parent_retired.status_code == 200, parent_retired.text
    restore = await admin_client.post(f"/api/tasks/{child.id}/restore", json={
        "expected_updated_at": child_retired.json()["updated_at"],
    })
    assert restore.status_code == 409
    assert "Restaura primero" in restore.json()["detail"]


async def test_reopening_completed_task_revalidates_its_retired_dependency(
    admin_client, db_session, admin_user,
):
    parent = await _carryover(db_session, admin_user.id, title="Completed parent")
    child = Task(
        title="Completed child", status=TaskStatus.completed, priority=TaskPriority.medium,
        completed_at=utc_now_naive(), depends_on=parent.id,
        assigned_to=admin_user.id, created_by=admin_user.id,
    )
    db_session.add(child)
    await db_session.flush()
    retired = await admin_client.post(f"/api/tasks/{parent.id}/carryover-decision", json={
        "action": "retire", "reason": "El dependiente ya terminó",
        "expected_updated_at": _token(parent),
    })
    assert retired.status_code == 200, retired.text
    annotation = await admin_client.put(f"/api/tasks/{child.id}", json={"title": "Título corregido"})
    assert annotation.status_code == 200, annotation.text
    reopened = await admin_client.put(f"/api/tasks/{child.id}", json={"status": "pending"})
    assert reopened.status_code == 409
    assert "retirada" in reopened.json()["detail"]


async def test_dependency_lock_serializes_with_retirement(engine):
    """A dependency validated after retirement waits and then sees retired state."""
    marker = "retirement-dependency-race"
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(email=f"{marker}@example.test", full_name="Actor", hashed_password="x",
                     role=UserRole.admin, is_active=True)
        target = Task(title=marker, status=TaskStatus.pending, priority=TaskPriority.medium,
                      scheduled_date=business_today() - timedelta(days=1))
        dependent = Task(title=f"{marker}-child", status=TaskStatus.pending, priority=TaskPriority.medium)
        # Dependent gets the lower id: this is the inverse order that used to
        # deadlock when each session locked its own row before the parent.
        setup.add_all([actor, dependent, target])
        await setup.commit()
        actor_id, target_id, dependent_id = actor.id, target.id, dependent.id
        assert dependent_id < target_id

    first_locked = asyncio.Event()
    release = asyncio.Event()

    async def retire():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            task = await lock_task_for_cas(db, target_id, (await db.get(Task, target_id)).updated_at)
            task.retired_at, task.retired_reason = utc_now_naive(), "Carrera"
            await db.flush()
            first_locked.set()
            await release.wait()
            await db.commit()

    async def add_dependency():
        await first_locked.wait()
        async with AsyncSession(engine, expire_on_commit=False) as db:
            actor = await db.get(User, actor_id)
            child = await db.get(Task, dependent_id, with_for_update=True)
            with pytest.raises(Exception) as exc:
                await update_task(db, child, {"depends_on": target_id}, actor=actor)
            assert getattr(exc.value, "status_code", None) == 409
            await db.rollback()

    retire_task = asyncio.create_task(retire())
    dependency_task = asyncio.create_task(add_dependency())
    await first_locked.wait()
    await asyncio.sleep(0.05)
    assert not dependency_task.done()
    release.set()
    await asyncio.gather(retire_task, dependency_task)

    async with AsyncSession(engine) as cleanup:
        for entity_id in (dependent_id, target_id):
            row = await cleanup.get(Task, entity_id)
            if row is not None:
                await cleanup.delete(row)
        actor = await cleanup.get(User, actor_id)
        if actor is not None:
            await cleanup.delete(actor)
        await cleanup.commit()


async def test_bulk_reopen_waits_for_parent_before_locking_child(engine):
    """Bulk status changes follow the same parent-before-child lock order as Undo."""
    marker = "retirement-bulk-lock-order"
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        actor = User(email=f"{marker}@example.test", full_name="Actor", hashed_password="x",
                     role=UserRole.admin, is_active=True)
        parent = Task(title=f"{marker}-parent", status=TaskStatus.pending,
                      priority=TaskPriority.medium)
        setup.add_all([actor, parent])
        await setup.flush()
        child = Task(title=f"{marker}-child", status=TaskStatus.completed,
                     priority=TaskPriority.medium, depends_on=parent.id,
                     completed_at=utc_now_naive())
        setup.add(child)
        await setup.commit()
        actor_id, parent_id, child_id = actor.id, parent.id, child.id
        assert parent_id < child_id

    release_parent = asyncio.Event()
    parent_locked = asyncio.Event()

    async def hold_parent():
        async with AsyncSession(engine) as db:
            await db.execute(select(Task).where(Task.id == parent_id).with_for_update())
            parent_locked.set()
            await release_parent.wait()
            await db.commit()

    async def bulk_reopen():
        await parent_locked.wait()
        async with AsyncSession(engine, expire_on_commit=False) as db:
            actor = await db.get(User, actor_id)
            return await bulk_update_tasks(
                BulkUpdateBody(ids=[child_id], updates={"status": "pending"}), db, actor,
            )

    holder = asyncio.create_task(hold_parent())
    updater = asyncio.create_task(bulk_reopen())
    await parent_locked.wait()
    await asyncio.sleep(0.05)
    assert not updater.done()
    # The updater is waiting on the lower parent id, so it cannot yet hold the child.
    async with AsyncSession(engine) as observer:
        locked_child = await observer.scalar(
            select(Task.id).where(Task.id == child_id).with_for_update(nowait=True)
        )
        assert locked_child == child_id
        await observer.rollback()

    release_parent.set()
    result = await updater
    await holder
    assert result["updated"] == result["requested"] == 1
    assert result["failed"] == 0
    assert len(result["results"]) == 1
    assert result["results"][0]["updated"] is True

    async with AsyncSession(engine) as cleanup:
        for entity_id in (child_id, parent_id):
            row = await cleanup.get(Task, entity_id)
            if row is not None:
                await cleanup.delete(row)
        actor = await cleanup.get(User, actor_id)
        if actor is not None:
            await cleanup.delete(actor)
        await cleanup.commit()


async def test_cas_epoch_supports_legacy_timestamptz_physical_column(engine):
    """No datetime bind is compared to the column, even on the legacy type."""
    marker = "retirement-cas-timestamptz"
    task_id = user_id = None
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE tasks ALTER COLUMN updated_at TYPE timestamptz "
                "USING updated_at AT TIME ZONE 'UTC'"
            ))
        async with AsyncSession(engine, expire_on_commit=False) as db:
            user = User(email=f"{marker}@example.test", full_name="Actor", hashed_password="x",
                        role=UserRole.admin, is_active=True)
            task = Task(title=marker, status=TaskStatus.pending, priority=TaskPriority.medium)
            db.add_all([user, task])
            await db.commit()
            user_id, task_id = user.id, task.id
            expected = task.updated_at.astimezone(timezone(timedelta(hours=-4)))
            locked = await lock_task_for_cas(db, task.id, expected)
            assert locked.id == task.id
            await db.rollback()
    finally:
        if task_id is not None:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": task_id})
                await conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE tasks ALTER COLUMN updated_at TYPE timestamp "
                "USING updated_at AT TIME ZONE 'UTC'"
            ))

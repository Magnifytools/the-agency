from datetime import date, timedelta
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import (
    ChangeLog, Client, ClientStatus, Project, ProjectStatus, Task,
    TaskRecurrenceOccurrence, TaskStatus,
)
from backend.services.recurrence import generate_recurring_instances

pytestmark = pytest.mark.integration


async def test_preview_is_read_only_and_pause_round_trip(admin_client, db_session):
    weekday = min(date.today().weekday(), 4)
    before = (await db_session.execute(select(func.count(Task.id)))).scalar_one()
    preview = await admin_client.post("/api/tasks/recurrence-preview", json={
        "is_recurring": True,
        "recurrence_pattern": "weekly",
        "recurrence_day": weekday,
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["state"] == "active"
    after = (await db_session.execute(select(func.count(Task.id)))).scalar_one()
    assert after == before

    created = await admin_client.post("/api/tasks", json={
        "title": "Plantilla pausa",
        "is_recurring": True,
        "recurrence_pattern": "weekly",
        "recurrence_day": weekday,
    })
    assert created.status_code == 201, created.text
    paused = await admin_client.put(
        f"/api/tasks/{created.json()['id']}", json={"recurrence_paused": True}
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["recurrence_paused_at"] is not None
    assert paused.json()["recurrence_summary"]["state"] == "paused"

    spoof_create = await admin_client.post("/api/tasks", json={
        "title": "Hijo falso", "recurring_parent_id": created.json()["id"],
        "recurrence_occurrence_date": date.today().isoformat(),
    })
    assert spoof_create.status_code == 422
    spoof_update = await admin_client.put(f"/api/tasks/{created.json()['id']}", json={
        "recurring_parent_id": None, "recurrence_occurrence_date": date.today().isoformat(),
    })
    assert spoof_update.status_code == 422

    legacy_preview = await admin_client.post("/api/tasks/recurrence-preview", json={
        "is_recurring": True, "recurrence_pattern": "biweekly",
        "recurrence_day": 0, "recurrence_anchor_date": None,
    })
    new_preview = await admin_client.post("/api/tasks/recurrence-preview", json={
        "is_recurring": True, "recurrence_pattern": "biweekly", "recurrence_day": 0,
    })
    assert "ISO" in legacy_preview.json()["label"]
    assert " a partir de " in new_preview.json()["label"]


async def test_new_and_transitioned_biweekly_rules_get_anchor(admin_client):
    new_rule = await admin_client.post("/api/tasks", json={
        "title": "Bisemanal nueva", "is_recurring": True,
        "recurrence_pattern": "biweekly", "recurrence_day": 0,
    })
    assert new_rule.status_code == 201, new_rule.text
    assert new_rule.json()["recurrence_anchor_date"] is not None
    weekly = await admin_client.post("/api/tasks", json={
        "title": "Semanal que cambia", "is_recurring": True,
        "recurrence_pattern": "weekly", "recurrence_day": 0,
    })
    transitioned = await admin_client.put(f"/api/tasks/{weekly.json()['id']}", json={
        "recurrence_pattern": "biweekly",
    })
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["recurrence_anchor_date"] is not None
    anchor = transitioned.json()["recurrence_anchor_date"]
    cleared = await admin_client.put(f"/api/tasks/{weekly.json()['id']}", json={
        "recurrence_anchor_date": None,
    })
    assert cleared.status_code == 422
    unchanged = await admin_client.get(f"/api/tasks/{weekly.json()['id']}")
    assert unchanged.json()["recurrence_anchor_date"] == anchor


async def test_pause_null_is_rejected_but_omission_preserves_state(admin_client):
    created = await admin_client.post("/api/tasks", json={
        "title": "Pause tri-state", "is_recurring": True,
        "recurrence_pattern": "weekly", "recurrence_day": 0,
    })
    task_id = created.json()["id"]
    paused = await admin_client.put(f"/api/tasks/{task_id}", json={"recurrence_paused": True})
    assert paused.status_code == 200
    paused_at = paused.json()["recurrence_paused_at"]
    rejected = await admin_client.put(f"/api/tasks/{task_id}", json={"recurrence_paused": None})
    assert rejected.status_code == 422
    renamed = await admin_client.put(f"/api/tasks/{task_id}", json={"title": "Still paused"})
    assert renamed.status_code == 200
    assert renamed.json()["recurrence_paused_at"] == paused_at


async def test_pause_resume_reconciles_only_today_without_backfill(admin_client, db_session):
    today = date.today()
    created = await admin_client.post("/api/tasks", json={
        "title": "Pausa sin backfill", "is_recurring": True,
        "recurrence_pattern": "daily",
        "recurrence_anchor_date": (today - timedelta(days=30)).isoformat(),
    })
    template_id = created.json()["id"]
    paused = await admin_client.put(
        f"/api/tasks/{template_id}", json={"recurrence_paused": True}
    )
    assert paused.status_code == 200
    assert await generate_recurring_instances(db_session, target_date=today) == 0
    resumed = await admin_client.put(
        f"/api/tasks/{template_id}", json={"recurrence_paused": False}
    )
    assert resumed.status_code == 200
    expected = 1 if today.weekday() < 5 else 0
    assert await generate_recurring_instances(db_session, target_date=today) == expected
    children = list((await db_session.execute(select(Task).where(
        Task.recurring_parent_id == template_id,
    ))).scalars())
    assert len(children) == expected
    assert all(child.recurrence_occurrence_date == today for child in children)


async def test_generator_is_idempotent_and_inherits_creator(admin_client, db_session):
    today = date.today()
    created = await admin_client.post("/api/tasks", json={
        "title": "Plantilla materializable",
        "is_recurring": True,
        "recurrence_pattern": "monthly",
        "recurrence_day": today.day,
        "recurrence_end_date": today.isoformat(),
    })
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    assert await generate_recurring_instances(db_session, target_date=today) == 1
    assert await generate_recurring_instances(db_session, target_date=today) == 0
    instance = (await db_session.execute(
        select(Task).where(Task.recurring_parent_id == template_id)
    )).scalar_one()
    assert instance.created_by == admin_client.test_user.id
    assert instance.recurrence_occurrence_date == today
    instance.scheduled_date = today + timedelta(days=3)
    await db_session.commit()
    assert await generate_recurring_instances(db_session, target_date=today) == 0


async def test_distinct_occurrences_can_be_rescheduled_to_same_day(admin_client, db_session):
    monday = date(2026, 9, 21)
    response = await admin_client.post("/api/tasks", json={
        "title": "Plantilla reprogramable", "is_recurring": True,
        "recurrence_pattern": "weekly", "recurrence_day": 0,
    })
    template_id = response.json()["id"]
    assert await generate_recurring_instances(db_session, target_date=monday) == 1
    assert await generate_recurring_instances(db_session, target_date=monday + timedelta(days=7)) == 1
    children = list((await db_session.execute(
        select(Task).where(Task.recurring_parent_id == template_id).order_by(Task.id)
    )).scalars())
    children[0].scheduled_date = monday + timedelta(days=10)
    children[1].scheduled_date = monday + timedelta(days=10)
    await db_session.commit()
    assert children[0].recurrence_occurrence_date != children[1].recurrence_occurrence_date


async def test_deleting_materialized_template_is_actionable(admin_client, db_session):
    today = date.today()
    response = await admin_client.post("/api/tasks", json={
        "title": "Plantilla con historial", "is_recurring": True,
        "recurrence_pattern": "monthly", "recurrence_day": today.day,
    })
    template_id = response.json()["id"]
    await generate_recurring_instances(db_session, target_date=today)
    deleted = await admin_client.delete(f"/api/tasks/{template_id}")
    assert deleted.status_code == 409
    assert "Páusala" in deleted.json()["detail"]


async def test_deleting_generated_child_does_not_regenerate_consumed_date(admin_client, db_session):
    today = date.today()
    response = await admin_client.post("/api/tasks", json={
        "title": "Plantilla con recibo", "is_recurring": True,
        "recurrence_pattern": "monthly", "recurrence_day": today.day,
    })
    template_id = response.json()["id"]
    assert await generate_recurring_instances(db_session, target_date=today) == 1
    child_id = (await db_session.execute(select(Task.id).where(
        Task.recurring_parent_id == template_id,
    ))).scalar_one()
    deleted = await admin_client.delete(f"/api/tasks/{child_id}")
    assert deleted.status_code == 204, deleted.text
    receipt = (await db_session.execute(select(TaskRecurrenceOccurrence).where(
        TaskRecurrenceOccurrence.template_id == template_id,
        TaskRecurrenceOccurrence.date == today,
    ))).scalar_one()
    await db_session.refresh(receipt)
    assert receipt.task_id is None
    assert await generate_recurring_instances(db_session, target_date=today) == 0
    assert (await db_session.execute(select(func.count(Task.id)).where(
        Task.recurring_parent_id == template_id,
    ))).scalar_one() == 0


async def test_undo_generated_child_relinks_receipt_and_keeps_same_identity(admin_client, db_session):
    today = date.today()
    created = await admin_client.post("/api/tasks", json={
        "title": "Undo occurrence", "is_recurring": True,
        "recurrence_pattern": "monthly", "recurrence_day": today.day,
    })
    template_id = created.json()["id"]
    await generate_recurring_instances(db_session, target_date=today)
    child_id = (await db_session.execute(select(Task.id).where(
        Task.recurring_parent_id == template_id,
    ))).scalar_one()
    deleted = await admin_client.delete(f"/api/tasks/{child_id}")
    assert deleted.status_code == 204
    change = (await db_session.execute(select(ChangeLog).where(
        ChangeLog.user_id == admin_client.test_user.id,
        ChangeLog.entity_type == "task",
        ChangeLog.entity_id == child_id,
        ChangeLog.action == "delete",
    ).order_by(ChangeLog.id.desc()).limit(1))).scalar_one()
    undone = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert undone.status_code == 200, undone.text
    restored = await db_session.get(Task, child_id)
    assert restored is not None
    assert restored.recurrence_occurrence_date == today
    receipt = (await db_session.execute(select(TaskRecurrenceOccurrence).where(
        TaskRecurrenceOccurrence.template_id == template_id,
        TaskRecurrenceOccurrence.date == today,
    ))).scalar_one()
    await db_session.refresh(receipt)
    assert receipt.task_id == child_id
    assert await generate_recurring_instances(db_session, target_date=today) == 0


async def test_undo_refuses_receipt_linked_to_different_task_before_marking_undone(admin_client, db_session):
    today = date.today()
    created = await admin_client.post("/api/tasks", json={
        "title": "Undo conflict", "is_recurring": True,
        "recurrence_pattern": "monthly", "recurrence_day": today.day,
    })
    template_id = created.json()["id"]
    await generate_recurring_instances(db_session, target_date=today)
    child_id = (await db_session.execute(select(Task.id).where(
        Task.recurring_parent_id == template_id,
    ))).scalar_one()
    assert (await admin_client.delete(f"/api/tasks/{child_id}")).status_code == 204
    change = (await db_session.execute(select(ChangeLog).where(
        ChangeLog.user_id == admin_client.test_user.id,
        ChangeLog.entity_id == child_id,
        ChangeLog.action == "delete",
    ).order_by(ChangeLog.id.desc()).limit(1))).scalar_one()
    decoy = Task(title="Receipt decoy", status=TaskStatus.pending)
    db_session.add(decoy)
    await db_session.flush()
    receipt = (await db_session.execute(select(TaskRecurrenceOccurrence).where(
        TaskRecurrenceOccurrence.template_id == template_id,
        TaskRecurrenceOccurrence.date == today,
    ))).scalar_one()
    receipt.task_id = decoy.id
    await db_session.commit()
    response = await admin_client.post(f"/api/changes/{change.id}/undo")
    assert response.status_code == 409
    await db_session.refresh(change)
    assert change.undone_at is None
    assert await db_session.get(Task, child_id) is None


async def test_legacy_child_observed_today_gets_receipt_without_identity_rewrite(admin_client, db_session):
    today = date.today()
    template = Task(
        title="Legacy template", status=TaskStatus.pending, is_recurring=True,
        recurrence_pattern="monthly", recurrence_day=today.day,
    )
    db_session.add(template)
    await db_session.flush()
    child = Task(
        title="Legacy child", status=TaskStatus.pending, is_recurring=False,
        recurring_parent_id=template.id, scheduled_date=today,
        recurrence_occurrence_date=None,
    )
    db_session.add(child)
    await db_session.commit()
    assert await generate_recurring_instances(db_session, target_date=today) == 0
    await db_session.refresh(child)
    assert child.recurrence_occurrence_date is None
    receipt = (await db_session.execute(select(TaskRecurrenceOccurrence).where(
        TaskRecurrenceOccurrence.template_id == template.id,
        TaskRecurrenceOccurrence.date == today,
    ))).scalar_one()
    assert receipt.task_id == child.id
    deleted = await admin_client.delete(f"/api/tasks/{child.id}")
    assert deleted.status_code == 204
    assert await generate_recurring_instances(db_session, target_date=today) == 0


async def test_paused_invalid_and_inactive_scope_templates_do_not_generate(db_session):
    target = date(2026, 9, 21)
    inactive_client = Client(name="Inactive recurrence", status=ClientStatus.paused)
    active_client = Client(name="Active recurrence", status=ClientStatus.active)
    db_session.add_all([inactive_client, active_client])
    await db_session.flush()
    inactive_project = Project(
        name="Inactive project recurrence", client_id=active_client.id,
        status=ProjectStatus.on_hold,
    )
    db_session.add(inactive_project)
    await db_session.flush()
    from datetime import datetime
    templates = [
        Task(title="Paused", status=TaskStatus.pending, is_recurring=True,
             recurrence_pattern="weekly", recurrence_day=0,
             recurrence_paused_at=datetime(2026, 9, 20)),
        Task(title="Invalid", status=TaskStatus.pending, is_recurring=True,
             recurrence_pattern="monthly", recurrence_day=31),
        Task(title="Blocked client", status=TaskStatus.pending, is_recurring=True,
             recurrence_pattern="weekly", recurrence_day=0, client_id=inactive_client.id),
        Task(title="Blocked project", status=TaskStatus.pending, is_recurring=True,
             recurrence_pattern="weekly", recurrence_day=0,
             client_id=active_client.id, project_id=inactive_project.id),
    ]
    db_session.add_all(templates)
    await db_session.commit()
    assert await generate_recurring_instances(db_session, target_date=target) == 0
    assert (await db_session.execute(select(func.count(Task.id)).where(
        Task.recurring_parent_id.in_([task.id for task in templates]),
    ))).scalar_one() == 0


async def test_bulk_delete_template_with_receipt_returns_recurrence_reason(admin_client, db_session):
    today = date.today()
    created = await admin_client.post("/api/tasks", json={
        "title": "Bulk protected", "is_recurring": True,
        "recurrence_pattern": "monthly", "recurrence_day": today.day,
    })
    template_id = created.json()["id"]
    await generate_recurring_instances(db_session, target_date=today)
    response = await admin_client.post("/api/tasks/bulk/delete", json={"ids": [template_id]})
    assert response.status_code == 200
    assert response.json()["errors"] == 1
    assert "plantillas" in response.json()["detail"]


async def test_concurrent_generators_create_one_instance_and_no_journal(engine):
    """Real PostgreSQL locks and unique identity converge across two sessions."""
    target = date(2026, 9, 21)
    title = f"Concurrent recurrence {uuid4().hex}"
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        template = Task(
            title=title, status=TaskStatus.pending, is_recurring=True,
            recurrence_pattern="weekly", recurrence_day=0,
        )
        setup.add(template)
        await setup.commit()
        template_id = template.id
        journal_before = (await setup.execute(select(func.count(ChangeLog.id)))).scalar_one()

    async def run_once() -> int:
        async with sessions() as session:
            return await generate_recurring_instances(session, target_date=target)

    from backend.services.change_journal import set_actor
    set_actor(987654321)
    try:
        assert sorted(await asyncio.gather(run_once(), run_once())) == [0, 1]
    finally:
        set_actor(None)
    async with sessions() as verify:
        children = (await verify.execute(select(func.count(Task.id)).where(
            Task.recurring_parent_id == template_id,
            Task.recurrence_occurrence_date == target,
        ))).scalar_one()
        journal = (await verify.execute(select(func.count(ChangeLog.id)))).scalar_one()
        assert children == 1
        assert journal == journal_before
        await verify.execute(TaskRecurrenceOccurrence.__table__.delete().where(
            TaskRecurrenceOccurrence.template_id == template_id
        ))
        await verify.execute(Task.__table__.delete().where(
            (Task.id == template_id) | (Task.recurring_parent_id == template_id)
        ))
        await verify.commit()


async def test_legacy_adoption_locks_observed_child_before_delete(engine):
    """Delete waits until today's observed legacy child has a durable receipt."""
    target = date(2026, 9, 21)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        template = Task(
            title=f"Legacy race {uuid4().hex}", status=TaskStatus.pending,
            is_recurring=True, recurrence_pattern="weekly", recurrence_day=0,
        )
        setup.add(template)
        await setup.flush()
        child = Task(
            title="Legacy observed child", status=TaskStatus.pending,
            recurring_parent_id=template.id, scheduled_date=target,
            recurrence_occurrence_date=None,
        )
        setup.add(child)
        await setup.commit()
        template_id, child_id = template.id, child.id

    observed = asyncio.Event()
    finish_adoption = asyncio.Event()

    class PausingSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            sql = str(statement)
            if "WHERE tasks.recurring_parent_id =" in sql and "tasks.scheduled_date" in sql and "FOR UPDATE" in sql:
                observed.set()
                await finish_adoption.wait()
            return result

    adopting_sessions = async_sessionmaker(engine, class_=PausingSession, expire_on_commit=False)

    async def adopt():
        async with adopting_sessions() as session:
            return await generate_recurring_instances(session, target_date=target)

    async def delete_child():
        async with sessions() as session:
            row = (await session.execute(
                select(Task).where(Task.id == child_id).with_for_update()
            )).scalar_one()
            await session.delete(row)
            await session.commit()

    adoption_task = asyncio.create_task(adopt())
    await asyncio.wait_for(observed.wait(), timeout=2)
    deletion_task = asyncio.create_task(delete_child())
    await asyncio.sleep(0.05)
    assert not deletion_task.done()
    finish_adoption.set()
    assert await adoption_task == 0
    await asyncio.wait_for(deletion_task, timeout=2)

    async with sessions() as verify:
        receipt = (await verify.execute(select(TaskRecurrenceOccurrence).where(
            TaskRecurrenceOccurrence.template_id == template_id,
            TaskRecurrenceOccurrence.date == target,
        ))).scalar_one()
        assert receipt.task_id is None
        assert await generate_recurring_instances(verify, target_date=target) == 0
        await verify.execute(TaskRecurrenceOccurrence.__table__.delete().where(
            TaskRecurrenceOccurrence.template_id == template_id
        ))
        await verify.execute(Task.__table__.delete().where(Task.id == template_id))
        await verify.commit()

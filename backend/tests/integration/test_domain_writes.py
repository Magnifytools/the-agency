"""Real PostgreSQL contracts for commit-free shared domain writers."""
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, GrowthIdea, Project, Task, TaskPriority, TaskStatus, TimeEntry, User, UserRole
from backend.api.routes.growth import convert_to_project as convert_growth_to_project
from backend.services.domain_writes import create_project, create_task, lock_task, update_task
from backend.services.time_writes import create_manual_time_entry


@pytest.mark.asyncio
async def test_shared_writers_preserve_null_zero_and_caller_rollback(engine):
    marker = "domain-writer-rollback"
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email=f"{marker}@example.test", full_name="Actor", hashed_password="x", role=UserRole.admin, is_active=True)
        client = Client(name=marker)
        db.add_all([actor, client])
        await db.flush()
        project = await create_project(db, {"name": marker, "client_id": client.id, "owner_id": None})
        task = await create_task(db, {
            "title": marker, "client_id": client.id, "project_id": project.id,
            "assigned_to": None, "scheduled_date": None, "actual_minutes": 0,
        }, actor=actor)
        assert task.assigned_to is None
        assert task.scheduled_date is None
        assert task.actual_minutes == 0
        await create_manual_time_entry(db, user_id=actor.id, task_id=task.id, minutes=15)
        assert task.actual_minutes == 15
        await db.rollback()

    async with AsyncSession(engine) as check:
        assert (await check.scalar(select(func.count()).select_from(Task).where(Task.title == marker))) == 0
        assert (await check.scalar(select(func.count()).select_from(Project).where(Project.name == marker))) == 0
        assert (await check.scalar(select(func.count()).select_from(TimeEntry).where(TimeEntry.notes == marker))) == 0


@pytest.mark.asyncio
async def test_shared_task_writer_rejects_cross_client_scope(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email="domain-scope@example.test", full_name="Actor", hashed_password="x", role=UserRole.admin, is_active=True)
        first = Client(name="domain-scope-a")
        second = Client(name="domain-scope-b")
        db.add_all([actor, first, second])
        await db.flush()
        project = await create_project(db, {"name": "domain-scope-project", "client_id": first.id})
        with pytest.raises(HTTPException) as exc:
            await create_task(db, {"title": "invalid", "client_id": second.id, "project_id": project.id}, actor=actor)
        assert exc.value.status_code == 422
        await db.rollback()


@pytest.mark.asyncio
async def test_shared_update_leaves_commit_and_rollback_to_caller(engine):
    marker = "domain-update-rollback"
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email=f"{marker}@example.test", full_name="Actor", hashed_password="x", role=UserRole.admin, is_active=True)
        task = Task(title=marker, status=TaskStatus.pending, priority=TaskPriority.medium)
        db.add_all([actor, task])
        await db.commit()
        task_id = task.id
        locked = await lock_task(db, task_id)
        await update_task(db, locked, {
            "status": TaskStatus.completed, "priority": TaskPriority.high,
        }, actor=actor)
        assert locked.completed_at is not None
        await db.rollback()
    async with AsyncSession(engine) as check:
        persisted = await check.get(Task, task_id)
        assert persisted.status == TaskStatus.pending
        assert persisted.priority == TaskPriority.medium
        assert persisted.completed_at is None
        await check.delete(persisted)
        await check.execute(delete(User).where(User.email == f"{marker}@example.test"))
        await check.commit()


@pytest.mark.asyncio
async def test_my_week_schedule_preserves_owner_admin_and_foreign_rules(
    admin_client, member_client, make_member_client, db_session,
):
    task = Task(title="schedule-owner", assigned_to=member_client.test_user.id,
                created_by=member_client.test_user.id, status=TaskStatus.pending)
    db_session.add(task)
    await db_session.flush()
    mine = await member_client.patch(f"/api/my-week/tasks/{task.id}/schedule", params={"scheduled_date": "2026-09-18"})
    assert mine.status_code == 200 and mine.json()["scheduled_date"] == "2026-09-18"
    stranger = await make_member_client([])
    denied = await stranger.patch(f"/api/my-week/tasks/{task.id}/schedule", params={"scheduled_date": "2026-09-19"})
    assert denied.status_code == 403
    changed = await admin_client.patch(f"/api/my-week/tasks/{task.id}/schedule", params={"scheduled_date": "2026-09-20"})
    assert changed.status_code == 200 and changed.json()["scheduled_date"] == "2026-09-20"
    await stranger.aclose()


@pytest.mark.asyncio
async def test_growth_conversion_rolls_back_entity_and_link_on_commit_failure(engine, monkeypatch):
    marker = "growth-atomic-conversion"
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(email=f"{marker}@example.test", full_name="Actor", hashed_password="x", role=UserRole.admin, is_active=True)
        client = Client(name=marker)
        idea = GrowthIdea(title=marker)
        db.add_all([actor, client, idea])
        await db.commit()
        ids = actor.id, client.id, idea.id

        async def fail_commit():
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated"):
            await convert_growth_to_project(idea.id, client.id, None, db, actor)
        await db.rollback()

    async with AsyncSession(engine) as check:
        stored = await check.get(GrowthIdea, ids[2])
        assert stored.project_id is None
        assert (await check.scalar(select(func.count()).select_from(Project).where(Project.name == f"[Buffer] {marker}"))) == 0
        await check.delete(stored)
        await check.execute(delete(Client).where(Client.id == ids[1]))
        await check.execute(delete(User).where(User.id == ids[0]))
        await check.commit()

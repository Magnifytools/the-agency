"""Real PostgreSQL contracts for commit-free shared domain writers."""
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, Project, Task, TimeEntry, User, UserRole
from backend.services.domain_writes import create_project, create_task
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

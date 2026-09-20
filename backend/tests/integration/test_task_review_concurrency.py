"""Task→Project policy checks cannot deadlock Project→Task Undo or accept stale policy."""
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, Project, Task, TaskStatus, User, UserPermission, UserRole
from backend.services.domain_writes import lock_task, update_task


@pytest.mark.asyncio
async def test_completion_contending_with_policy_update_fails_fast_then_rechecks(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner = User(email=f"owner-{uuid4().hex}@example.test", full_name="Owner", hashed_password="x", role=UserRole.member)
        actor = User(email=f"actor-{uuid4().hex}@example.test", full_name="Actor", hashed_password="x", role=UserRole.member)
        client = Client(name="Review contention")
        setup.add_all([owner, actor, client])
        await setup.flush()
        setup.add(UserPermission(user_id=actor.id, module="tasks", can_read=True, can_write=True))
        project = Project(name="Contended policy", client_id=client.id, owner_id=owner.id, requires_task_review=False)
        setup.add(project)
        await setup.flush()
        task = Task(title="Contended completion", project_id=project.id, client_id=client.id, status=TaskStatus.pending)
        setup.add(task)
        await setup.commit()
        owner_id, actor_id, client_id, project_id, task_id = owner.id, actor.id, client.id, project.id, task.id
    try:
        async with AsyncSession(engine, expire_on_commit=False) as task_db, AsyncSession(engine, expire_on_commit=False) as policy_db:
            # Opposite lock orders exist intentionally; the policy check must
            # reject contention rather than wait for the cycle to deadlock.
            task = await lock_task(task_db, task_id)
            actor = await task_db.get(User, actor_id)
            policy = await policy_db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            policy.requires_task_review = True
            await policy_db.flush()
            with pytest.raises(HTTPException) as contention:
                await asyncio.wait_for(update_task(task_db, task, {"status": TaskStatus.completed}, actor=actor), timeout=2)
            assert contention.value.status_code == 409
            assert "cambiando" in contention.value.detail
            await task_db.rollback()
            await policy_db.commit()

            task = await lock_task(task_db, task_id)
            actor = await task_db.get(User, actor_id)
            with pytest.raises(HTTPException) as policy_required:
                await update_task(task_db, task, {"status": TaskStatus.completed}, actor=actor)
            assert policy_required.value.status_code == 409
            assert "requiere revisión" in policy_required.value.detail
            await task_db.rollback()
            task = await lock_task(task_db, task_id)
            assert task.status == TaskStatus.pending
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(Task).where(Task.id == task_id))
            await cleanup.execute(delete(Project).where(Project.id == project_id))
            await cleanup.execute(delete(Client).where(Client.id == client_id))
            await cleanup.execute(delete(UserPermission).where(UserPermission.user_id.in_([owner_id, actor_id])))
            await cleanup.execute(delete(User).where(User.id.in_([owner_id, actor_id])))
            await cleanup.commit()

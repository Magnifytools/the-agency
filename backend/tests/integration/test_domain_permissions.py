from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.inbox import convert_to_task
from backend.api.routes.tasks import BulkDeleteBody, bulk_delete_tasks
from backend.db.models import (
    Client, ClientStatus, InboxNote, InboxNoteStatus, Project, ProjectStatus,
    Task, User, UserRole,
)
from backend.schemas.inbox import ConvertToTaskBody


@pytest.mark.asyncio
async def test_inbox_conversion_requires_tasks_write(make_member_client):
    client = await make_member_client([("tasks", True, False)])
    try:
        note = await client.post("/api/inbox", json={"raw_text": "Captura sin permiso"})
        assert note.status_code == 201, note.text
        response = await client.post(
            f"/api/inbox/{note.json()['id']}/convert-to-task", json={"client_id": 1}
        )
        assert response.status_code == 403
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_finalization_requires_clients_write(make_member_client):
    client = await make_member_client([("clients", True, False)])
    try:
        response = await client.delete("/api/clients/999999")
        assert response.status_code == 403
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_inbox_conversion_rejects_cross_client_project(
    admin_client, db_session
):
    first = Client(name="Cliente Inbox A", status=ClientStatus.active)
    second = Client(name="Cliente Inbox B", status=ClientStatus.active)
    db_session.add_all([first, second])
    await db_session.flush()
    project = Project(name="Proyecto B", client_id=second.id, status=ProjectStatus.active)
    note = InboxNote(
        user_id=admin_client.test_user.id, raw_text="Cruce", status=InboxNoteStatus.pending,
    )
    db_session.add_all([project, note])
    await db_session.flush()

    response = await admin_client.post(
        f"/api/inbox/{note.id}/convert-to-task",
        json={"client_id": first.id, "project_id": project.id},
    )
    assert response.status_code == 422
    assert (await db_session.execute(
        select(func.count()).select_from(Task).where(Task.title == "Cruce")
    )).scalar_one() == 0


@pytest.mark.asyncio
async def test_inbox_concurrent_retry_returns_one_task(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = User(
            email="inbox-concurrent@test.local", full_name="Inbox Concurrent",
            hashed_password="unused", role=UserRole.admin, is_active=True,
        )
        client = Client(name="Inbox Concurrent Client", status=ClientStatus.active)
        setup.add_all([user, client])
        await setup.flush()
        note = InboxNote(
            user_id=user.id, raw_text="Una sola tarea", status=InboxNoteStatus.pending,
            client_id=client.id,
        )
        setup.add(note)
        await setup.commit()
        note_id, user_id, client_id = note.id, user.id, client.id

    async def run_conversion():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            actor = await session.get(User, user_id)
            return await convert_to_task(
                note_id, ConvertToTaskBody(client_id=client_id), db=session, user=actor
            )

    try:
        first, second = await asyncio.gather(run_conversion(), run_conversion())
        assert first["task_id"] == second["task_id"]
        async with AsyncSession(engine) as verify:
            tasks = (await verify.execute(
                select(Task).where(Task.created_by == user_id, Task.title == "Una sola tarea")
            )).scalars().all()
            assert len(tasks) == 1
    finally:
        async with AsyncSession(engine) as cleanup:
            found_note = await cleanup.get(InboxNote, note_id)
            if found_note:
                await cleanup.delete(found_note)
            for task in (await cleanup.execute(
                select(Task).where(Task.created_by == user_id)
            )).scalars().all():
                await cleanup.delete(task)
            found_client = await cleanup.get(Client, client_id)
            if found_client:
                await cleanup.delete(found_client)
            found_user = await cleanup.get(User, user_id)
            if found_user:
                await cleanup.delete(found_user)
            await cleanup.commit()


class _FailCommitOnce:
    def __init__(self, session):
        self.session = session
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def commit(self):
        if not self.failed:
            self.failed = True
            raise RuntimeError("simulated commit failure")
        await self.session.commit()


@pytest.mark.asyncio
async def test_bulk_delete_reports_only_committed_and_retry_succeeds(
    engine,
):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        task = Task(title="Bulk retry")
        setup.add(task)
        await setup.commit()
        task_id = task.id

    async with AsyncSession(engine) as failing:
        with pytest.raises(HTTPException) as exc:
            await bulk_delete_tasks(
                BulkDeleteBody(ids=[task_id]), db=_FailCommitOnce(failing), _=None,
            )
        assert exc.value.status_code == 500

    async with AsyncSession(engine) as verify:
        assert await verify.get(Task, task_id) is not None

    async with AsyncSession(engine) as retry:
        result = await bulk_delete_tasks(
            BulkDeleteBody(ids=[task_id]), db=retry, _=None,
        )
        assert result["deleted"] == 1

    async with AsyncSession(engine) as verify:
        assert await verify.get(Task, task_id) is None

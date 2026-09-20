from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.users import sync_user_permissions
from backend.core.security import create_access_token
from backend.db.database import get_db
from backend.db.models import ChangeLog, Task, TaskStatus, User, UserPermission, UserRole
from backend.services.write_access import require_current_write


pytestmark = pytest.mark.integration


@asynccontextmanager
async def _independent_client(engine, user_id: int):
    from backend.main import app

    previous = app.dependency_overrides.get(get_db)

    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = sessions
    token = create_access_token({"sub": str(user_id)})
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            yield client
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


async def _member(db, *, writable: bool = True) -> User:
    user = User(
        email=f"fresh-write-{uuid4().hex}@test.local",
        full_name="Fresh writer",
        hashed_password="unused",
        role=UserRole.member,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserPermission(
        user_id=user.id,
        module="tasks",
        can_read=True,
        can_write=writable,
    ))
    await db.commit()
    return user


async def test_fresh_permission_row_overrides_stale_actor_relationship(db_session):
    member = await _member(db_session, writable=True)
    stale_actor = SimpleNamespace(
        id=member.id,
        role=UserRole.member,
        permissions=[SimpleNamespace(module="tasks", can_write=False)],
    )

    await require_current_write(db_session, stale_actor, {"tasks"})


async def test_revoked_permission_and_inactive_actor_are_denied_from_current_db_state(
    db_session,
):
    member = await _member(db_session, writable=True)
    stale_actor = SimpleNamespace(id=member.id, role=UserRole.admin)
    await db_session.execute(delete(UserPermission).where(
        UserPermission.user_id == member.id,
        UserPermission.module == "tasks",
    ))
    await db_session.commit()

    with pytest.raises(HTTPException) as revoked:
        await require_current_write(db_session, stale_actor, {"tasks"})
    assert revoked.value.status_code == 403

    member = await db_session.get(User, member.id)
    member.is_active = False
    await db_session.commit()
    with pytest.raises(HTTPException) as inactive:
        await require_current_write(db_session, stale_actor, {"tasks"})
    assert inactive.value.status_code == 403


async def test_admin_bypasses_rows_but_not_hidden_module(db_session, admin_user, monkeypatch):
    await require_current_write(db_session, admin_user, {"tasks"})

    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "tasks")
    with pytest.raises(HTTPException) as hidden:
        await require_current_write(db_session, admin_user, {"tasks"})
    assert hidden.value.status_code == 403


async def test_none_actor_is_an_explicit_automatic_writer(db_session, monkeypatch):
    monkeypatch.setenv("AGENCY_HIDDEN_MODULES", "tasks")
    assert await require_current_write(db_session, None, {"tasks"}) is None


async def test_user_acl_writer_contention_returns_retryable_conflict(engine):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        member = await _member(setup, writable=True)
        member_id = member.id

    writer = AsyncSession(engine, expire_on_commit=False)
    checker = AsyncSession(engine, expire_on_commit=False)
    try:
        await writer.execute(
            select(User.id).where(User.id == member_id).with_for_update(key_share=True)
        )
        with pytest.raises(HTTPException) as conflict:
            await require_current_write(
                checker, SimpleNamespace(id=member_id), {"tasks"},
            )
        assert conflict.value.status_code == 409
        assert "vuelve a intentarlo" in conflict.value.detail
        await checker.rollback()
    finally:
        await writer.rollback()
        await checker.close()
        await writer.close()


async def test_task_http_rechecks_permission_after_waiting_for_task_lock(
    engine,
):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        admin = User(
            email=f"race-admin-{uuid4().hex}@test.local", full_name="Race admin",
            hashed_password="unused", role=UserRole.admin, is_active=True,
        )
        member = User(
            email=f"race-member-{uuid4().hex}@test.local", full_name="Race member",
            hashed_password="unused", role=UserRole.member, is_active=True,
        )
        task = Task(title="Permission race task", status=TaskStatus.pending)
        setup.add_all([admin, member, task])
        await setup.flush()
        setup.add(UserPermission(
            user_id=member.id, module="tasks", can_read=True, can_write=True,
        ))
        await setup.commit()
        task_id, member_id, admin_id = task.id, member.id, admin.id

    holder = AsyncSession(engine, expire_on_commit=False)
    request = None
    async with _independent_client(engine, member_id) as member_client:
        try:
            await holder.execute(select(Task).where(Task.id == task_id).with_for_update())
            request = asyncio.create_task(member_client.put(
                f"/api/tasks/{task_id}", json={"title": "Must not commit"},
            ))
            await asyncio.sleep(0.1)
            assert not request.done()

            async with AsyncSession(engine, expire_on_commit=False) as revoke_db:
                admin = await revoke_db.get(User, admin_id)
                await sync_user_permissions(member_id, [], revoke_db, admin)

            await holder.rollback()
            response = await asyncio.wait_for(request, timeout=5)
            assert response.status_code == 403, response.text
        finally:
            if holder.in_transaction():
                await holder.rollback()
            await holder.close()

    async with AsyncSession(engine) as verify:
        assert (await verify.get(Task, task_id)).title == "Permission race task"


async def test_undo_http_rechecks_permission_after_waiting_for_change_lock(
    engine,
):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        admin = User(
            email=f"undo-admin-{uuid4().hex}@test.local", full_name="Undo admin",
            hashed_password="unused", role=UserRole.admin, is_active=True,
        )
        member = User(
            email=f"undo-member-{uuid4().hex}@test.local", full_name="Undo member",
            hashed_password="unused", role=UserRole.member, is_active=True,
        )
        task = Task(title="Undo permission race", status=TaskStatus.pending)
        setup.add_all([admin, member, task])
        await setup.flush()
        setup.add(UserPermission(
            user_id=member.id, module="tasks", can_read=True, can_write=True,
        ))
        await setup.commit()
        task_id, member_id, admin_id = task.id, member.id, admin.id

    async with _independent_client(engine, member_id) as member_client:
        changed = await member_client.put(
            f"/api/tasks/{task_id}", json={"title": "Edited before revoke"},
        )
        assert changed.status_code == 200, changed.text
        async with AsyncSession(engine) as lookup:
            change_id = await lookup.scalar(
                select(ChangeLog.id)
                .where(ChangeLog.user_id == member_id)
                .order_by(ChangeLog.id.desc())
                .limit(1)
            )
        assert change_id is not None

        holder = AsyncSession(engine, expire_on_commit=False)
        request = None
        try:
            await holder.execute(
                select(ChangeLog).where(ChangeLog.id == change_id).with_for_update()
            )
            request = asyncio.create_task(
                member_client.post(f"/api/changes/{change_id}/undo")
            )
            await asyncio.sleep(0.1)
            assert not request.done()

            async with AsyncSession(engine, expire_on_commit=False) as revoke_db:
                admin = await revoke_db.get(User, admin_id)
                await sync_user_permissions(member_id, [], revoke_db, admin)

            await holder.rollback()
            response = await asyncio.wait_for(request, timeout=5)
            assert response.status_code == 403, response.text
        finally:
            if holder.in_transaction():
                await holder.rollback()
            await holder.close()

    async with AsyncSession(engine) as verify:
        assert (await verify.get(Task, task_id)).title == "Edited before revoke"
        assert (await verify.get(ChangeLog, change_id)).undone_at is None

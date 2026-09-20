"""Permission writers share the recipient lock used by incident reconciliation."""

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.invitations import update_user_permissions
from backend.api.routes.users import sync_default_permissions_all_users, sync_user_permissions
from backend.db.models import Notification, Task, TaskStatus, User, UserPermission, UserRole
from backend.schemas.invitation import PermissionItem, UserPermissionsUpdate
from backend.services.incidents import reconcile_recipient


NOW = datetime(2026, 9, 19, 10)


async def _permissions(engine, user_id: int):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        rows = (await db.execute(
            select(UserPermission.module, UserPermission.can_read, UserPermission.can_write)
            .where(UserPermission.user_id == user_id)
            .order_by(UserPermission.module, UserPermission.id)
        )).all()
        return [(row.module, row.can_read, row.can_write) for row in rows]


async def _create_users(engine):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = User(
            email=f"permission-admin-{uuid4().hex}@test.local",
            full_name="Permission admin",
            hashed_password="test",
            role=UserRole.admin,
            is_active=True,
        )
        member = User(
            email=f"permission-member-{uuid4().hex}@test.local",
            full_name="Permission member",
            hashed_password="test",
            role=UserRole.member,
            is_active=True,
        )
        db.add_all([admin, member])
        await db.flush()
        db.add(UserPermission(user_id=member.id, module="tasks", can_read=True, can_write=False))
        await db.commit()
        return admin, member


async def _cleanup(engine, *user_ids):
    async with engine.begin() as conn:
        await conn.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
        await conn.execute(delete(Task).where(Task.assigned_to.in_(user_ids)))
        # Task deletion is journaled and may materialize activity during flush;
        # clear any recipient rows created by that cascade before deleting users.
        await conn.execute(delete(Notification).where(Notification.user_id.in_(user_ids)))
        await conn.execute(delete(UserPermission).where(UserPermission.user_id.in_(user_ids)))
        await conn.execute(delete(User).where(User.id.in_(user_ids)))


async def test_permission_revocation_waits_for_reconciliation_and_next_pass_resolves(
    engine, monkeypatch,
):
    admin, member = await _create_users(engine)
    entered_collection = asyncio.Event()
    release_collection = asyncio.Event()
    import backend.services.incidents as incidents

    original_collect = incidents.collect_task_conditions

    async def paused_collect(db, user_id, now):
        entered_collection.set()
        await release_collection.wait()
        return await original_collect(db, user_id, now)

    monkeypatch.setattr(incidents, "collect_task_conditions", paused_collect)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(Task(
            title="Concurrent permission task",
            assigned_to=member.id,
            status=TaskStatus.pending,
            due_date=NOW - timedelta(days=1),
        ))
        await db.commit()

    async def reconcile():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await reconcile_recipient(db, member.id, now=NOW)
            await db.commit()

    async def revoke():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            return await sync_user_permissions(member.id, [], db, admin)

    try:
        reconcile_task = asyncio.create_task(reconcile())
        await asyncio.wait_for(entered_collection.wait(), timeout=5)
        revoke_task = asyncio.create_task(revoke())
        await asyncio.sleep(0.1)
        assert not revoke_task.done()
        release_collection.set()
        await asyncio.wait_for(asyncio.gather(reconcile_task, revoke_task), timeout=10)
        assert await _permissions(engine, member.id) == []

        async with AsyncSession(engine, expire_on_commit=False) as db:
            await reconcile_recipient(db, member.id, now=NOW)
            await db.commit()
        async with AsyncSession(engine, expire_on_commit=False) as db:
            incident = (await db.execute(select(Notification).where(
                Notification.user_id == member.id,
                Notification.incident_state.is_not(None),
            ))).scalar_one()
            assert incident.incident_state == "resolved"
            assert incident.incident_resolution_reason == "permission_lost"
    finally:
        release_collection.set()
        await _cleanup(engine, admin.id, member.id)


async def test_reconciliation_reloads_permissions_after_waiting_for_revocation(engine):
    admin, member = await _create_users(engine)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add(Task(
            title="Permission snapshot task",
            assigned_to=member.id,
            status=TaskStatus.pending,
            due_date=NOW - timedelta(days=1),
        ))
        await db.commit()

    writer = AsyncSession(engine, expire_on_commit=False)
    try:
        # Hold the same recipient lock as the real permission endpoints, while
        # the permission deletion remains invisible to other transactions.
        await writer.execute(
            select(User.id)
            .where(User.id == member.id)
            .with_for_update(key_share=True)
        )
        await writer.execute(
            delete(UserPermission).where(
                UserPermission.user_id == member.id,
                UserPermission.module == "tasks",
            )
        )
        await writer.flush()

        async def reconcile():
            async with AsyncSession(engine, expire_on_commit=False) as db:
                result = await reconcile_recipient(db, member.id, now=NOW)
                await db.commit()
                return result

        reconcile_task = asyncio.create_task(reconcile())
        await asyncio.sleep(0.1)
        assert not reconcile_task.done()

        await writer.commit()
        assert await asyncio.wait_for(reconcile_task, timeout=10) == {"created": 0, "changed": 0}
        async with AsyncSession(engine, expire_on_commit=False) as db:
            count = len((await db.execute(select(Notification.id).where(
                Notification.user_id == member.id,
                Notification.incident_state.is_not(None),
            ))).all())
            assert count == 0
    finally:
        await writer.rollback()
        await writer.close()
        await _cleanup(engine, admin.id, member.id)


async def test_both_permission_replace_endpoints_serialize_complete_results(engine):
    admin, member = await _create_users(engine)

    async def replace_modules():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await sync_user_permissions(member.id, ["tasks"], db, admin)

    async def replace_capabilities():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await update_user_permissions(
                member.id,
                UserPermissionsUpdate(permissions=[
                    PermissionItem(module="projects", can_read=True, can_write=False),
                ]),
                db,
                admin,
            )

    try:
        await asyncio.wait_for(asyncio.gather(replace_modules(), replace_capabilities()), timeout=10)
        rows = await _permissions(engine, member.id)
        assert rows in [
            [("projects", True, False)],
            [("tasks", True, True)],
        ]
    finally:
        await _cleanup(engine, admin.id, member.id)


async def test_default_sync_and_exact_replace_have_a_serial_outcome(engine):
    admin, member = await _create_users(engine)

    async def add_defaults():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await sync_default_permissions_all_users(db, admin)

    async def replace_exactly():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await update_user_permissions(
                member.id,
                UserPermissionsUpdate(permissions=[
                    PermissionItem(module="digests", can_read=True, can_write=False),
                ]),
                db,
                admin,
            )

    defaults = {"dashboard", "clients", "tasks", "projects", "timesheet", "pm"}
    try:
        await asyncio.wait_for(asyncio.gather(add_defaults(), replace_exactly()), timeout=10)
        rows = await _permissions(engine, member.id)
        modules = {module for module, _read, _write in rows}
        assert len(rows) == len(modules)
        assert modules in ({"digests"}, defaults | {"digests"})
    finally:
        await _cleanup(engine, admin.id, member.id)

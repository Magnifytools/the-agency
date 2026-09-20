"""Task writers and incident reconciliation share one ordered row-lock protocol."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.routes.tasks import BulkDeleteBody, bulk_delete_tasks, update_task
from backend.db.models import (
    Notification,
    Task,
    TaskStatus,
    User,
    UserPermission,
    UserRole,
)
from backend.schemas.task import TaskUpdate
from backend.services.incidents import reconcile_recipient
from backend.startup.background_tasks import _reset_advanced_tasks

NOW = datetime(2026, 9, 20, 10)  # noqa: DTZ001 - application stores naive UTC


class PausingLockSession(AsyncSession):
    """Pause immediately after this session acquires its first task row lock."""

    def __init__(
        self, *args, lock_acquired: asyncio.Event, release_lock: asyncio.Event, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._lock_acquired = lock_acquired
        self._release_lock = release_lock
        self._paused = False

    async def execute(self, statement, *args, **kwargs):
        result = await super().execute(statement, *args, **kwargs)
        sql = str(statement).upper()
        if not self._paused and "FROM TASKS" in sql and "FOR UPDATE" in sql:
            self._paused = True
            self._lock_acquired.set()
            await self._release_lock.wait()
        return result


async def _actor_and_task(
    engine, *, status=TaskStatus.pending, advanced_at=None, overdue=False
):
    async with AsyncSession(engine, expire_on_commit=False) as db:
        actor = User(
            email=f"task-lock-{uuid4().hex}@test.local",
            full_name="Task lock actor",
            hashed_password="test",
            role=UserRole.member,
            is_active=True,
        )
        db.add(actor)
        await db.flush()
        db.add(
            UserPermission(
                user_id=actor.id,
                module="tasks",
                can_read=True,
                can_write=True,
            )
        )
        task = Task(
            title="Task lock source",
            assigned_to=actor.id,
            status=status,
            advanced_at=advanced_at,
            due_date=NOW - timedelta(days=1) if overdue else None,
            is_recurring=False,
        )
        db.add(task)
        await db.commit()
        return actor, task.id


def _wait_for_task_lock_statement(engine, *, select_fragment: str):
    started = asyncio.Event()

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.upper().split())
        if "FOR UPDATE" in normalized and select_fragment in normalized:
            started.set()

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    return started, capture


async def test_reset_waits_for_public_edit_and_rechecks_eligibility(
    engine, monkeypatch
):
    actor, task_id = await _actor_and_task(
        engine,
        status=TaskStatus.advanced,
        advanced_at=date(2026, 9, 19),
    )
    from backend.db import database
    from backend.startup import background_tasks

    monkeypatch.setattr(
        database,
        "async_session",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    monkeypatch.setattr(background_tasks, "business_today", lambda: date(2026, 9, 20))

    writer_locked = asyncio.Event()
    release_writer = asyncio.Event()
    writer = PausingLockSession(
        bind=engine,
        expire_on_commit=False,
        lock_acquired=writer_locked,
        release_lock=release_writer,
    )
    writer_task = asyncio.create_task(
        update_task(
            task_id,
            TaskUpdate(status=TaskStatus.pending),
            writer,
            actor,
        )
    )
    await asyncio.wait_for(writer_locked.wait(), timeout=5)

    reset_started, listener = _wait_for_task_lock_statement(
        engine,
        select_fragment="SELECT TASKS.ID",
    )
    try:
        reset_task = asyncio.create_task(_reset_advanced_tasks())
        await asyncio.wait_for(reset_started.wait(), timeout=5)
        assert not reset_task.done()
        release_writer.set()
        await asyncio.wait_for(asyncio.gather(writer_task, reset_task), timeout=10)
    finally:
        release_writer.set()
        event.remove(engine.sync_engine, "before_cursor_execute", listener)
        await writer.close()

    async with AsyncSession(engine, expire_on_commit=False) as db:
        row = await db.get(Task, task_id)
        assert row is not None
        assert row.status == TaskStatus.pending
        assert row.advanced_at is None


async def test_bulk_delete_blocks_reconcile_then_deleted_source_is_not_created(engine):
    actor, task_id = await _actor_and_task(engine, overdue=True)
    writer_locked = asyncio.Event()
    release_writer = asyncio.Event()
    writer = PausingLockSession(
        bind=engine,
        expire_on_commit=False,
        lock_acquired=writer_locked,
        release_lock=release_writer,
    )
    delete_task = asyncio.create_task(
        bulk_delete_tasks(
            BulkDeleteBody(ids=[task_id]),
            writer,
            actor,
        )
    )
    await asyncio.wait_for(writer_locked.wait(), timeout=5)

    reconcile_started, listener = _wait_for_task_lock_statement(
        engine,
        select_fragment="SELECT TASKS.ID, TASKS.TITLE",
    )

    async def reconcile():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            result = await reconcile_recipient(db, actor.id, now=NOW)
            await db.commit()
            return result

    try:
        reconcile_task = asyncio.create_task(reconcile())
        await asyncio.wait_for(reconcile_started.wait(), timeout=5)
        assert not reconcile_task.done()
        release_writer.set()
        deleted, reconciled = await asyncio.wait_for(
            asyncio.gather(delete_task, reconcile_task),
            timeout=10,
        )
    finally:
        release_writer.set()
        event.remove(engine.sync_engine, "before_cursor_execute", listener)
        await writer.close()

    assert deleted == {"deleted": 1, "errors": 0, "requested": 1, "detail": None}
    assert reconciled == {"created": 0, "changed": 0}
    async with AsyncSession(engine, expire_on_commit=False) as db:
        assert await db.get(Task, task_id) is None
        assert (
            await db.scalar(
                select(Notification.id).where(
                    Notification.user_id == actor.id,
                    Notification.entity_id == task_id,
                    Notification.incident_state.is_not(None),
                )
            )
            is None
        )

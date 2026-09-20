"""Recurrence upgrades preserve history and enforce one dated occurrence."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from backend.startup.recurrence_schema import ensure_recurrence_schema
from backend.startup.readiness import check_database_ready


@pytest.mark.parametrize("duplicates", [False, True])
async def test_upgrade_preserves_historical_tasks_and_calendar(engine, duplicates):
    schema = "recurrence_upgrade_" + uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_async_engine(engine.url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with isolated.begin() as conn:
            await conn.execute(text("""CREATE TABLE tasks (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                recurring_parent_id INTEGER, scheduled_date DATE,
                recurrence_pattern TEXT, recurrence_day INTEGER)
            """))
            await conn.execute(text("""INSERT INTO tasks VALUES
                (1, 'Original template', NULL, NULL, 'biweekly', 4),
                (2, 'Historical child', 1, '2026-09-18', NULL, NULL),
                (3, 'Undated history', 1, NULL, NULL, NULL),
                (4, 'Other undated history', 1, NULL, NULL, NULL),
                (5, 'Independent task', NULL, '2026-09-18', NULL, NULL)
            """))
            if duplicates:
                await conn.execute(text("INSERT INTO tasks VALUES (6, 'Another original', 1, '2026-09-18', NULL, NULL)"))
                # A partially upgraded installation with conflicting stable
                # identities must fail atomically, preserving both tasks.
                await conn.execute(text("ALTER TABLE tasks ADD COLUMN recurrence_occurrence_date DATE"))
                await conn.execute(text("UPDATE tasks SET recurrence_occurrence_date='2026-09-18' WHERE id IN (2,6)"))
            before = (await conn.execute(text("SELECT * FROM tasks ORDER BY id"))).all()
        if duplicates:
            with pytest.raises(IntegrityError):
                await ensure_recurrence_schema(isolated)
            async with isolated.connect() as conn:
                assert (await conn.execute(text("SELECT * FROM tasks ORDER BY id"))).all() == before
                # DDL rolled back together, leaving the previous app's schema.
                assert await conn.scalar(text("""SELECT count(*) FROM information_schema.columns
                    WHERE table_schema=:schema AND table_name='tasks'
                    AND column_name='recurrence_anchor_date'"""), {"schema": schema}) == 0
        else:
            await asyncio.gather(ensure_recurrence_schema(isolated), ensure_recurrence_schema(isolated))
            async with isolated.begin() as conn:
                assert (await conn.execute(text("""SELECT id, title, recurring_parent_id,
                    scheduled_date, recurrence_pattern, recurrence_day FROM tasks ORDER BY id"""))).all() == before
                assert await conn.scalar(text("""SELECT count(*) FROM tasks
                    WHERE recurrence_anchor_date IS NOT NULL OR recurrence_paused_at IS NOT NULL
                    OR recurrence_occurrence_date IS NOT NULL""")) == 0
                await conn.execute(text("""INSERT INTO tasks(id,title,recurring_parent_id,scheduled_date,recurrence_occurrence_date)
                    VALUES (6,'New child',1,'2026-10-02','2026-10-02')"""))
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text("""INSERT INTO tasks(id,title,recurring_parent_id,scheduled_date,recurrence_occurrence_date)
                            VALUES (7,'Duplicate despite reschedule',1,'2026-10-03','2026-10-02')"""))
                await conn.execute(text("""INSERT INTO tasks(id,title,recurring_parent_id,scheduled_date,recurrence_occurrence_date) VALUES
                    (7,'Other occurrence same work day',1,'2026-10-02','2026-10-16'),
                    (8,'Different template',9,'2026-10-02','2026-10-02'),
                    (9,'Independent same day',NULL,'2026-10-02',NULL)"""))
            await ensure_recurrence_schema(isolated)
            async with isolated.connect() as conn:
                assert await conn.scalar(text("SELECT count(*) FROM tasks")) == 9
            async with isolated.begin() as conn:
                await conn.execute(text("""INSERT INTO task_recurrence_occurrences(template_id,date,task_id)
                    VALUES(1,'2026-10-02',6)"""))
                await conn.execute(text("DELETE FROM tasks WHERE id=6"))
                receipt = (await conn.execute(text("""SELECT template_id,date,task_id,created_at
                    FROM task_recurrence_occurrences"""))).one()
                assert receipt.template_id == 1
                assert receipt.task_id is None
                assert receipt.created_at is not None
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text("""INSERT INTO task_recurrence_occurrences(template_id,date)
                            VALUES(1,'2026-10-02')"""))
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text("DELETE FROM tasks WHERE id=1"))
    finally:
        await isolated.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def test_readiness_rejects_wrong_recurrence_index_predicate(engine):
    await check_database_ready(engine)
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX uq_task_recurring_occurrence"))
        await conn.execute(text("""CREATE UNIQUE INDEX uq_task_recurring_occurrence
            ON tasks(recurring_parent_id,recurrence_occurrence_date) WHERE is_recurring"""))
    try:
        with pytest.raises(RuntimeError, match="unique index"):
            await check_database_ready(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP INDEX uq_task_recurring_occurrence"))
        await ensure_recurrence_schema(engine)
    await check_database_ready(engine)

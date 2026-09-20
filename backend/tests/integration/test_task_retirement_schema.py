"""Upgrade the published P16 schema without changing historical work."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Base, User, UserRole
from backend.startup import deployment_schema, schema_baseline
from backend.startup.inbox_recovery_schema_v2 import MIGRATION as INBOX_MIGRATION
from backend.startup.job_runtime_schema import MIGRATION as JOB_MIGRATION
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.task_retirement_schema import apply


async def _empty(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def published_schema(engine):
    await _empty(engine)
    await run_schema_migrations(
        engine, (*schema_baseline.MIGRATIONS, JOB_MIGRATION, INBOX_MIGRATION),
        schema_baseline.preflight,
    )
    yield
    await _empty(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


@pytest.mark.parametrize("legacy_tz", [False, True])
async def test_upgrade_preserves_all_task_and_time_values(engine, legacy_tz):
    async with AsyncSession(engine) as db:
        db.add(User(id=101, email="schema@example.test", full_name="Schema",
                    hashed_password="synthetic", role=UserRole.admin))
        await db.commit()
    async with engine.begin() as conn:
        if legacy_tz:
            # Production combines naive Task timestamps with legacy aware Inbox timestamps.
            await conn.execute(text("ALTER TABLE inbox_notes ALTER COLUMN updated_at TYPE timestamptz USING updated_at AT TIME ZONE 'UTC', ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE 'UTC'"))
        await conn.execute(text("""
            INSERT INTO tasks (id,title,status,priority,is_inbox,is_recurring,
                created_by,assigned_to,due_date,scheduled_date,actual_minutes,completed_at,
                created_at,updated_at,waiting_for,follow_up_date)
            VALUES
            (201,'Legacy completed','completed','medium',false,false,101,101,
             '2026-01-01','2026-01-02',42,NULL,'2025-01-01','2026-01-03',NULL,NULL),
            (202,'Legacy waiting','waiting','high',false,false,101,NULL,
             '2026-01-01','2026-01-02',NULL,NULL,'2025-01-01','2026-01-03','Respuesta','2026-01-04')
        """))
        await conn.execute(text("""
            INSERT INTO time_entries (task_id,user_id,minutes,date,notes,created_at,updated_at)
            VALUES (201,101,42,'2026-01-02','Historical time','2026-01-02','2026-01-02')
        """))
        before_tasks = (await conn.execute(text("SELECT to_jsonb(t) FROM tasks t ORDER BY id"))).scalars().all()
        before_time = (await conn.execute(text("SELECT to_jsonb(t) FROM time_entries t ORDER BY id"))).scalars().all()
        ledger = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after_tasks = (await conn.execute(text("SELECT to_jsonb(t)-'retired_at'-'retired_reason' FROM tasks t ORDER BY id"))).scalars().all()
        assert after_tasks == before_tasks
        assert (await conn.execute(text("SELECT to_jsonb(t) FROM time_entries t ORDER BY id"))).scalars().all() == before_time
        assert (await conn.execute(text("SELECT retired_at,retired_reason FROM tasks ORDER BY id"))).all() == [(None, None)] * 2
        after_ledger = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
        assert {row.version for row in after_ledger} == {migration.version for migration in deployment_schema.MIGRATIONS}
        assert set(ledger) <= set(after_ledger)


@pytest.mark.parametrize("damage", ["length", "timezone", "nullable", "default", "check", "unvalidated"])
async def test_incompatible_state_rejected_without_recording_migration(engine, damage):
    async with engine.begin() as conn:
        await apply(conn)
        if damage == "length":
            await conn.execute(text("ALTER TABLE tasks ALTER COLUMN retired_reason TYPE varchar(20)"))
        elif damage == "timezone":
            await conn.execute(text("ALTER TABLE tasks ALTER COLUMN retired_at TYPE timestamptz"))
        elif damage == "nullable":
            await conn.execute(text("ALTER TABLE tasks ALTER COLUMN retired_at SET NOT NULL"))
        elif damage == "default":
            await conn.execute(text("ALTER TABLE tasks ALTER COLUMN retired_at SET DEFAULT now()"))
        else:
            await conn.execute(text("ALTER TABLE tasks DROP CONSTRAINT ck_tasks_retirement_pair"))
            suffix = " NOT VALID" if damage == "unvalidated" else ""
            expression = (
                "(retired_at IS NULL AND retired_reason IS NULL) OR "
                "(retired_at IS NOT NULL AND retired_reason IS NOT NULL AND length(btrim(retired_reason)) > 0)"
                if damage == "unvalidated" else "retired_at IS NULL OR retired_reason IS NOT NULL"
            )
            await conn.execute(text(f"ALTER TABLE tasks ADD CONSTRAINT ck_tasks_retirement_pair CHECK ({expression}){suffix}"))
    with pytest.raises(RuntimeError, match="tasks"):
        await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions")) == 4


async def test_runtime_drift_does_not_repair_or_reapply_published_step(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE tasks DROP CONSTRAINT ck_tasks_retirement_pair"))
    with pytest.raises(RuntimeError, match="tasks retirement constraint"):
        await deployment_schema.check_deployment_ready(engine)
    with pytest.raises(RuntimeError, match="tasks retirement constraint"):
        await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM pg_constraint WHERE conname='ck_tasks_retirement_pair'")) == 0

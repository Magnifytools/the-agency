"""The procedure columns are additive and leave existing tasks untouched."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.task_procedure_schema import MIGRATION, apply, verify

pytestmark = pytest.mark.integration


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def published_previous(engine):
    await reset(engine)
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO tasks (id,title,status,priority,is_inbox,is_recurring,created_at,updated_at)
            VALUES (1,'Plantilla antigua','pending','medium',false,true,'2026-01-01','2026-01-02')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_twice_preserves_tasks_without_backfill(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(t) FROM tasks t WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after = await conn.scalar(text(
            "SELECT to_jsonb(t)-'procedure_text'-'procedure_url'-'sort_rank' FROM tasks t WHERE id=1"
        ))
        assert after == before
        row = (await conn.execute(text(
            "SELECT procedure_text, procedure_url FROM tasks WHERE id=1"
        ))).one()
        assert tuple(row) == (None, None)


@pytest.mark.parametrize("damage", [
    "ALTER TABLE tasks ALTER COLUMN procedure_url TYPE VARCHAR(100)",
    "ALTER TABLE tasks ALTER COLUMN procedure_text SET DEFAULT ''",
    "ALTER TABLE tasks DROP COLUMN procedure_text",
])
async def test_drift_is_rejected(engine, damage):
    async with engine.begin() as conn:
        await apply(conn)
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            await verify(conn)

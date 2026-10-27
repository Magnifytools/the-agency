"""El arrastre de horas es una columna aditiva, apagada en los proyectos existentes."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.project_hours_carryover_schema import MIGRATION, verify
from backend.startup.schema_runner import run_schema_migrations

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
            INSERT INTO clients (id,name,contract_type,status,currency,is_internal,is_intermediary_deal,created_at,updated_at)
            VALUES (1,'Existing client','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
        await conn.execute(text("""
            INSERT INTO projects(id,name,client_id,status,progress_percent,is_recurring,monthly_hours_budget,
                created_at,updated_at)
            VALUES (1,'Retainer',1,'active',0,true,20,'2026-01-01','2026-01-02')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def _through_this_step(engine):
    plan = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION) + 1]
    await run_schema_migrations(engine, plan, schema_baseline.preflight)


async def test_upgrade_twice_keeps_existing_projects_without_carryover(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(p) FROM projects p WHERE id=1"))
    await _through_this_step(engine)
    await _through_this_step(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT to_jsonb(p)-'hours_carryover' FROM projects p WHERE id=1")) == before
        assert await conn.scalar(text("SELECT hours_carryover FROM projects WHERE id=1")) is False


@pytest.mark.parametrize("damage", [
    "ALTER TABLE projects ALTER COLUMN hours_carryover DROP NOT NULL",
    "ALTER TABLE projects ALTER COLUMN hours_carryover SET DEFAULT true",
    "ALTER TABLE projects DROP COLUMN hours_carryover",
])
async def test_drift_is_rejected(engine, damage):
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

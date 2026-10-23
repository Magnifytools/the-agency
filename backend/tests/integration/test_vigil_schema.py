"""El paso de Vigil es aditivo y su contrato se verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.vigil_retirement_schema import MIGRATION as RETIREMENT
from backend.startup.vigil_schema import MIGRATION, verify

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
            VALUES (1,'Fit Generation','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def until_retirement(engine):
    """Todo el plan hasta justo antes de ``vigil_retirement_v1``, que borra lo de este paso."""
    plan = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(RETIREMENT)]
    await run_schema_migrations(engine, plan, schema_baseline.preflight)


async def test_upgrade_twice_keeps_clients_and_leaves_slug_empty(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(c) FROM clients c WHERE id=1"))
    await until_retirement(engine)
    await until_retirement(engine)
    async with engine.connect() as conn:
        await verify(conn)
        after = await conn.scalar(text("SELECT to_jsonb(c) - 'vigil_slug' - 'brand_terms' - 'seo_page_groups' - 'ga4_lead_events' FROM clients c WHERE id=1"))
        assert after == before
        assert await conn.scalar(text("SELECT vigil_slug FROM clients WHERE id=1")) is None


@pytest.mark.parametrize("damage", [
    "DROP INDEX uq_clients_vigil_slug",
    "ALTER TABLE clients ALTER COLUMN vigil_slug TYPE VARCHAR(50)",
    "ALTER TABLE vigil_summary DROP CONSTRAINT vigil_summary_pkey",
])
async def test_drift_is_rejected(engine, damage):
    await until_retirement(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

"""El paso de GA4 es aditivo y su contrato se verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.ga4_schema import MIGRATION, verify
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
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_twice_and_ready(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)


@pytest.mark.parametrize("damage", [
    "ALTER TABLE ga4_daily DROP COLUMN ai_sessions",
    "ALTER TABLE ga4_property_sync ALTER COLUMN error_code TYPE VARCHAR(10)",
    "ALTER TABLE ga4_daily DROP CONSTRAINT ga4_daily_pkey",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

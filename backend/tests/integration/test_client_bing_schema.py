"""El paso de la conexión de Bing es aditivo, idempotente y su contrato se verifica."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.client_bing_schema import MIGRATION, verify
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration

GOOD = ("INSERT INTO client_bing_connections (client_id, api_key, site_url) "
        "VALUES (5, 'v1:cifrada', 'https://www.sage.es/')")


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
            VALUES (5,'Sage','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def _through_this_step(engine):
    plan = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION) + 1]
    await run_schema_migrations(engine, plan, schema_baseline.preflight)


async def test_upgrade_twice_and_checks_hold(engine):
    await _through_this_step(engine)
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text(GOOD))
        assert await conn.scalar(text("SELECT status FROM client_bing_connections")) == "ok"
    for bad in (
        # Clave en claro.
        "INSERT INTO client_bing_connections (client_id, api_key, site_url) VALUES (5, 'abc123', 'https://www.sage.es/')",
        "INSERT INTO client_bing_connections (client_id, api_key, site_url) VALUES (5, 'v1:x', 'sage.es')",
        "INSERT INTO client_bing_connections (client_id, api_key, site_url, status) VALUES (5, 'v1:x', 'https://sage.es/', 'raro')",
        # Una sola conexión por cliente.
        GOOD,
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(bad))


async def test_deleting_the_client_takes_its_connection(engine):
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text(GOOD))
        await conn.execute(text("DELETE FROM clients WHERE id=5"))
        assert await conn.scalar(text("SELECT count(*) FROM client_bing_connections")) == 0


@pytest.mark.parametrize("damage", [
    "ALTER TABLE client_bing_connections ALTER COLUMN site_url TYPE VARCHAR(200)",
    "ALTER TABLE client_bing_connections ALTER COLUMN connected_at TYPE TIMESTAMP",
    "ALTER TABLE client_bing_connections DROP CONSTRAINT client_bing_connections_client_id_fkey",
    "ALTER TABLE client_bing_connections DROP CONSTRAINT ck_client_bing_connections_api_key",
])
async def test_drift_is_rejected(engine, damage):
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

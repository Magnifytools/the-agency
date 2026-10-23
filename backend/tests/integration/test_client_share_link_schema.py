"""El paso del enlace del cliente es aditivo y su contrato se verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.client_share_link_schema import MIGRATION, verify
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
            VALUES (1,'Fit Generation','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_twice_keeps_clients_and_starts_without_links(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(c) - 'vigil_slug' FROM clients c WHERE id=1"))  # la retira vigil_retirement_v1
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        # brand_terms y seo_page_groups llegan con pasos posteriores, vacíos.
        assert await conn.scalar(text("SELECT to_jsonb(c) - 'brand_terms' - 'seo_page_groups' - 'ga4_lead_events' FROM clients c WHERE id=1")) == before
        assert await conn.scalar(text("SELECT count(*) FROM client_share_links")) == 0


async def test_deleting_the_client_deletes_its_links(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO client_share_links (client_id, token_hash) VALUES (1, repeat('a', 64))"))
        await conn.execute(text("DELETE FROM clients WHERE id=1"))
        assert await conn.scalar(text("SELECT count(*) FROM client_share_links")) == 0


@pytest.mark.parametrize("damage", [
    "DROP INDEX uq_client_share_links_active",
    "DROP INDEX uq_client_share_links_token_hash",
    "ALTER TABLE client_share_links ALTER COLUMN token_hash TYPE VARCHAR(128)",
    "ALTER TABLE client_share_links ALTER COLUMN revoked_at TYPE TIMESTAMP",
    "ALTER TABLE client_share_links DROP CONSTRAINT client_share_links_client_id_fkey",
    "ALTER TABLE client_share_links DROP CONSTRAINT client_share_links_pkey",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

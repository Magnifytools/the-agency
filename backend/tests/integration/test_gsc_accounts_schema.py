"""Varias cuentas de Search Console: la cuenta ya conectada se conserva y caben más."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.gsc_accounts_schema import MIGRATION, verify
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
            INSERT INTO gsc_connection (id, google_email, refresh_token, status, connected_at)
            VALUES (1, 'Digital@Magnify.ing', 'v1:x', 'connected', '2026-10-18T10:00:00Z')
        """))
        await conn.execute(text("""
            INSERT INTO gsc_site_sync (site_url, last_data_date) VALUES ('sc-domain:fitgeneration.es', '2026-10-17')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_keeps_the_account_and_allows_more(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.begin() as conn:
        row = (await conn.execute(text("SELECT id, google_email, status FROM gsc_connection"))).one()
        assert tuple(row) == (1, "digital@magnify.ing", "connected")
        new_id = await conn.scalar(text("""
            INSERT INTO gsc_connection (google_email, refresh_token, status, connected_at)
            VALUES ('david@magnify.ing', 'v1:y', 'connected', now()) RETURNING id
        """))
        assert new_id == 2
        assert await conn.scalar(text("SELECT connection_id FROM gsc_site_sync")) is None
        with pytest.raises(Exception):
            async with conn.begin_nested():
                await conn.execute(text("""
                    INSERT INTO gsc_connection (google_email, refresh_token, status, connected_at)
                    VALUES ('david@magnify.ing', 'v1:z', 'connected', now())
                """))


@pytest.mark.parametrize("damage", [
    "ALTER TABLE gsc_connection ADD CONSTRAINT ck_gsc_connection_singleton CHECK (id = 1)",
    "ALTER TABLE gsc_connection ALTER COLUMN id DROP DEFAULT",
    "DROP INDEX uq_gsc_connection_google_email",
    "ALTER TABLE gsc_site_sync DROP COLUMN connection_id",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

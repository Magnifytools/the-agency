"""El paso de Accesos es aditivo y su contrato se verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.credentials_schema import MIGRATION, verify
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


async def test_upgrade_twice_keeps_clients_and_starts_empty(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(c) FROM clients c WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        # brand_terms y seo_page_groups llegan con pasos posteriores, vacíos.
        assert await conn.scalar(text("SELECT to_jsonb(c) - 'brand_terms' - 'seo_page_groups' FROM clients c WHERE id=1")) == before
        for table in ("credentials", "credential_shares", "credential_access_log"):
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


async def test_deleting_the_client_keeps_the_credential(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO credentials (id, name, secret_encrypted, client_id) VALUES (1, 'WP', 'v1:x', 1)"))
        await conn.execute(text("INSERT INTO credential_access_log (credential_id, credential_name, action) VALUES (1, 'WP', 'create')"))
        await conn.execute(text("DELETE FROM clients WHERE id=1"))
        assert await conn.scalar(text("SELECT client_id FROM credentials WHERE id=1")) is None
        await conn.execute(text("DELETE FROM credentials WHERE id=1"))
        assert await conn.scalar(text("SELECT credential_name FROM credential_access_log WHERE credential_id IS NULL")) == "WP"


@pytest.mark.parametrize("damage", [
    "ALTER TABLE credentials DROP CONSTRAINT ck_credentials_secret_encrypted",
    "ALTER TABLE credential_access_log DROP CONSTRAINT ck_credential_access_log_action",
    "ALTER TABLE credentials ALTER COLUMN secret_encrypted DROP NOT NULL",
    "ALTER TABLE credentials ALTER COLUMN name TYPE VARCHAR(100)",
    "ALTER TABLE credentials DROP CONSTRAINT credentials_client_id_fkey",
    "ALTER TABLE credential_shares DROP CONSTRAINT credential_shares_pkey",
    "ALTER TABLE credential_access_log DROP CONSTRAINT credential_access_log_credential_id_fkey",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

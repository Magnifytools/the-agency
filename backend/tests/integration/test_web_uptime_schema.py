"""El paso ``web_uptime_v1`` es aditivo, idempotente y su contrato se verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.web_uptime_schema import MIGRATION, verify

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
    assert deployment_schema.EXPECTED_SCHEMA_VERSION == MIGRATION.version
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT to_jsonb(c) FROM clients c WHERE id=1")) == before
        for table in ("web_uptime_targets", "web_uptime_state", "web_outages", "web_uptime_probes",
                      "client_web_settings"):
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


async def test_clean_install_runs_every_step(engine):
    await reset(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)


async def test_orm_create_all_satisfies_the_contract(engine):
    """``init_db``/la suite crean el esquema desde el ORM: debe cumplir el mismo contrato."""
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)


async def test_constraints_hold(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO web_uptime_targets (id, client_id, url) VALUES (1, 1, 'https://fit.es/')"))
        await conn.execute(text(
            "INSERT INTO web_outages (target_id, kind, started_at, confirmed_at) VALUES (1, 'down', now(), now())"
        ))
    for statement in (
        # Una sola caída abierta por objetivo.
        "INSERT INTO web_outages (target_id, kind, started_at, confirmed_at) VALUES (1, 'blocked', now(), now())",
        "INSERT INTO web_uptime_targets (client_id, url) VALUES (1, 'https://fit.es/')",
        "INSERT INTO client_web_settings (client_id, slack_webhook_url) VALUES (1, 'https://hooks.slack.com/services/T/B/X')",
        "INSERT INTO web_uptime_state (target_id, status) VALUES (1, 'roto')",
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(statement))
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE web_outages SET ended_at = now()"))
        await conn.execute(text(
            "INSERT INTO web_outages (target_id, kind, started_at, confirmed_at) VALUES (1, 'blocked', now(), now())"
        ))
        await conn.execute(text("INSERT INTO client_web_settings (client_id, slack_webhook_url) VALUES (1, 'v1:abc')"))
        # Borrar el cliente se lleva sus URLs, caídas y ajustes.
        await conn.execute(text("DELETE FROM clients WHERE id=1"))
        for table in ("web_uptime_targets", "web_outages", "client_web_settings"):
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


@pytest.mark.parametrize("damage", [
    "ALTER TABLE client_web_settings DROP CONSTRAINT ck_client_web_settings_webhook_encrypted",
    "ALTER TABLE web_outages DROP CONSTRAINT ck_web_outages_kind",
    "DROP INDEX uq_web_outages_open",
    "ALTER TABLE web_uptime_targets DROP CONSTRAINT uq_web_uptime_targets_client_url",
    "ALTER TABLE web_uptime_targets ALTER COLUMN url TYPE VARCHAR(200)",
    "ALTER TABLE web_uptime_state ALTER COLUMN next_check_at DROP NOT NULL",
    "ALTER TABLE web_uptime_probes DROP CONSTRAINT web_uptime_probes_target_id_fkey",
    "ALTER TABLE client_web_settings DROP CONSTRAINT client_web_settings_pkey",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

"""The origin column is additive and leaves historical requests untouched."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.usage_origin_schema import MIGRATION, apply


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def published_p25(engine):
    await reset(engine)
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO audit_logs(id,user_id,method,route_template,status_code,duration_ms,created_at,updated_at)
            VALUES (1,NULL,'GET','/api/tasks',200,12,'2026-01-01','2026-01-01')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_twice_preserves_history_without_backfill(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(a) FROM audit_logs a WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after = await conn.scalar(text("SELECT to_jsonb(a)-'client_origin' FROM audit_logs a WHERE id=1"))
        assert after == before
        assert await conn.scalar(text("SELECT client_origin FROM audit_logs WHERE id=1")) is None


@pytest.mark.parametrize("damage", ["nullable", "length", "type"])
async def test_origin_schema_drift_is_rejected_before_ledger_stamp(engine, damage):
    async with engine.begin() as conn:
        await apply(conn)
        statements = {
            "nullable": "ALTER TABLE audit_logs ALTER COLUMN client_origin SET NOT NULL",
            "length": "ALTER TABLE audit_logs ALTER COLUMN client_origin TYPE varchar(20)",
            "type": "ALTER TABLE audit_logs ALTER COLUMN client_origin TYPE text",
        }
        if damage == "nullable":
            await conn.execute(text("UPDATE audit_logs SET client_origin='unknown'"))
        await conn.execute(text(statements[damage]))
    with pytest.raises(RuntimeError, match="audit_logs.client_origin"):
        await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text(
            "SELECT count(*) FROM agency_schema_versions WHERE version=:version"
        ), {"version": MIGRATION.version}) == 0

"""El paso de los periodos saltados es aditivo, idempotente y su contrato se verifica."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.digest_period_skips_schema import MIGRATION, verify
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration

GOOD = ("INSERT INTO digest_period_skips (client_id, period_start, period_end, reason) "
        "VALUES (5, '2026-09-01', '2026-09-30', 'Vacaciones')")


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
        assert await conn.scalar(text("SELECT skipped_at IS NOT NULL FROM digest_period_skips"))
    for bad in (
        # Sin motivo (o sólo espacios).
        "INSERT INTO digest_period_skips (client_id, period_start, period_end, reason) VALUES (5, '2026-08-01', '2026-08-31', '   ')",
        # Fin antes que el inicio.
        "INSERT INTO digest_period_skips (client_id, period_start, period_end, reason) VALUES (5, '2026-08-31', '2026-08-01', 'x')",
        # Un salto por cliente y periodo.
        GOOD,
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(bad))


async def test_deleting_the_client_takes_its_skips(engine):
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text(GOOD))
        await conn.execute(text("DELETE FROM clients WHERE id=5"))
        assert await conn.scalar(text("SELECT count(*) FROM digest_period_skips")) == 0


@pytest.mark.parametrize("damage", [
    "ALTER TABLE digest_period_skips ALTER COLUMN reason TYPE VARCHAR(100)",
    "ALTER TABLE digest_period_skips ALTER COLUMN skipped_at TYPE TIMESTAMP",
    "ALTER TABLE digest_period_skips DROP CONSTRAINT digest_period_skips_client_id_fkey",
    "ALTER TABLE digest_period_skips DROP CONSTRAINT ck_digest_period_skips_reason",
    "ALTER TABLE digest_period_skips DROP CONSTRAINT uq_digest_period_skips_period",
])
async def test_drift_is_rejected(engine, damage):
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

"""El paso del informe SEO local es aditivo, idempotente y su contrato se verifica."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.local_reports_schema import MIGRATION, verify
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
        await conn.execute(text("""INSERT INTO client_local_report_configs (client_id, template, landing_url, settings, roadmap)
            VALUES (5, 'cigarral', 'https://ejemplo.com/restaurante/', '{}', '{"meses": {}}')"""))
        await conn.execute(text("""INSERT INTO client_local_reports (id, client_id, period_start, period_end, datos, roadmap)
            VALUES (1, 5, '2026-10-01', '2026-10-31', '{}', '{}')"""))
        await conn.execute(text("""INSERT INTO client_local_report_sources (report_id, kind, filename, content_type, content, size)
            VALUES (1, 'gbp_actual', 'a.csv', 'text/csv', 'x', 1)"""))
        assert await conn.scalar(text("SELECT inputs::text FROM client_local_reports")) == "{}"
    for bad in (
        "INSERT INTO client_local_report_configs (client_id, template, landing_url, settings, roadmap) VALUES (5, 'c', 'ftp://x', '{}', '{}')",
        "INSERT INTO client_local_reports (client_id, period_start, period_end, datos, roadmap) VALUES (5, '2026-10-31', '2026-10-01', '{}', '{}')",
        # Una sola versión abierta por periodo.
        "INSERT INTO client_local_reports (client_id, period_start, period_end, datos, roadmap) VALUES (5, '2026-10-01', '2026-10-31', '{}', '{}')",
        "UPDATE client_local_reports SET html = 'x'",
        "UPDATE client_local_reports SET delivered_at = now()",
        "UPDATE client_local_reports SET ai_status = 'pensando'",
        "INSERT INTO client_local_report_sources (report_id, kind, filename, content_type, content, size) VALUES (1, 'foto', 'a', 'b', 'x', 1)",
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(bad))
    async with engine.begin() as conn:
        # Entregada, ya puede abrirse otra del mismo periodo.
        await conn.execute(text("UPDATE client_local_reports SET html='x', pdf='y', generated_at=now(), delivered_at=now()"))
        await conn.execute(text("""INSERT INTO client_local_reports (client_id, period_start, period_end, datos, roadmap)
            VALUES (5, '2026-10-01', '2026-10-31', '{}', '{}')"""))


async def test_deleting_the_client_takes_everything(engine):
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text("""INSERT INTO client_local_reports (id, client_id, period_start, period_end, datos, roadmap)
            VALUES (1, 5, '2026-10-01', '2026-10-31', '{}', '{}')"""))
        await conn.execute(text("""INSERT INTO client_local_report_sources (report_id, kind, filename, content_type, content, size)
            VALUES (1, 'rastreo', 'a.csv', 'text/csv', 'x', 1)"""))
        await conn.execute(text("DELETE FROM clients WHERE id=5"))
        assert await conn.scalar(text("SELECT count(*) FROM client_local_report_sources")) == 0


@pytest.mark.parametrize("damage", [
    "ALTER TABLE client_local_reports ALTER COLUMN file_stem TYPE VARCHAR(60)",
    "ALTER TABLE client_local_reports DROP CONSTRAINT client_local_reports_client_id_fkey",
    "ALTER TABLE client_local_report_sources DROP CONSTRAINT ck_local_report_sources_kind",
    "ALTER TABLE client_local_report_configs ALTER COLUMN settings DROP NOT NULL",
])
async def test_drift_is_rejected(engine, damage):
    await _through_this_step(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

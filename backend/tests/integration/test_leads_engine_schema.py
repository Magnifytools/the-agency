"""El paso de lo heredado de The Engine (leads por landing y origen del
historial mensual) es aditivo: lo publicado sigue igual y su contrato se
verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.leads_engine_schema import MIGRATION, apply, verify
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
            VALUES (1,'Sage','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
        await conn.execute(text(
            "INSERT INTO gsc_query_monthly (site_url, month, query, clicks, impressions, weighted_position_sum) "
            "VALUES ('sc-domain:a.com', '2026-09-01', 'q', 1, 10, 30.0)"
        ))
        await conn.execute(text(
            "INSERT INTO ga4_property_sync (property_id, last_data_date) VALUES ('311111111', '2026-10-20')"
        ))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


def test_esta_en_el_plan():
    assert MIGRATION in deployment_schema.MIGRATIONS
    assert MIGRATION.version == "20261022_leads_engine_v1"


async def test_upgrade_twice_keeps_data_and_ready(engine):
    async with engine.connect() as conn:
        # vigil_slug lo retira un paso posterior (vigil_retirement_v1).
        before = await conn.scalar(text("SELECT to_jsonb(c) - 'vigil_slug' FROM clients c WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT to_jsonb(c) - 'ga4_lead_events' FROM clients c WHERE id=1")) == before
        assert await conn.scalar(text(
            "SELECT ga4_lead_events = '[\"generate_lead\"]'::jsonb FROM clients WHERE id=1")) is True
        # Lo que ya había en el historial es de Google.
        assert await conn.scalar(text("SELECT source FROM gsc_query_monthly")) == "google"
        row = (await conn.execute(text(
            "SELECT last_data_date, leads_backfilled_at, leads_events FROM ga4_property_sync"))).one()
        assert str(row.last_data_date) == "2026-10-20" and row.leads_backfilled_at is None and row.leads_events is None
        assert await conn.scalar(text("SELECT count(*) FROM ga4_lead_daily")) == 0


async def test_las_restricciones_se_cumplen(engine):
    await deployment_schema.migrate_schema(engine)
    for bad in (
        "UPDATE gsc_query_monthly SET source = 'otra'",
        "INSERT INTO ga4_lead_daily VALUES ('1', '2026-10-01', repeat('a', 2001), 'x', 1)",
    ):
        async with engine.begin() as conn:
            with pytest.raises(Exception):
                await conn.execute(text(bad))


async def test_instalacion_limpia(engine):
    await reset(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)


async def test_apply_es_idempotente(engine):
    async with engine.begin() as conn:
        await apply(conn)
        await apply(conn)
        await verify(conn)


async def test_el_orm_coincide_con_el_contrato(engine):
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)


@pytest.mark.parametrize("damage", [
    "ALTER TABLE clients ALTER COLUMN ga4_lead_events DROP NOT NULL",
    "ALTER TABLE clients ALTER COLUMN ga4_lead_events SET DEFAULT '[]'::jsonb",
    "ALTER TABLE ga4_lead_daily DROP CONSTRAINT ga4_lead_daily_pkey",
    "ALTER TABLE ga4_lead_daily DROP CONSTRAINT ck_ga4_lead_daily_landing_length",
    "ALTER TABLE ga4_lead_daily ALTER COLUMN channel TYPE VARCHAR(32)",
    "ALTER TABLE ga4_property_sync DROP COLUMN leads_covered_from",
    "ALTER TABLE gsc_query_monthly DROP CONSTRAINT ck_gsc_query_monthly_source",
    "ALTER TABLE gsc_query_monthly ALTER COLUMN source DROP NOT NULL",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

"""El paso de retirada de la fase 0 borra lo de los módulos eliminados y nada más."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.phase0_retirement_schema import (
    MIGRATION, RETIRED_COLUMNS, RETIRED_TABLES, verify,
)
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def tables(conn):
    return set((await conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
    ))).scalars())


async def columns(conn):
    return {tuple(r) for r in (await conn.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
    ))).all()}


@pytest_asyncio.fixture(autouse=True)
async def clean(engine):
    await reset(engine)
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def published_previous(engine):
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO clients (id,name,contract_type,status,currency,is_internal,is_intermediary_deal,
                                 aov,cif,created_at,updated_at)
            VALUES (1,'Parklex','monthly','active','EUR',false,false,90,'B123','2026-01-01','2026-01-02')
        """))
        await conn.execute(text("""
            INSERT INTO client_resources (client_id,label,url,resource_type,created_at,updated_at)
            VALUES (1,'Hoja','https://x.test','spreadsheet','2026-01-01','2026-01-01')
        """))


async def test_upgrade_drops_retired_tables_and_columns_and_keeps_the_rest(engine):
    await published_previous(engine)
    async with engine.connect() as conn:
        client_before = await conn.scalar(text(
            "SELECT to_jsonb(c) - 'aov' - 'ltv' - 'conversion_rate' - 'business_model'"
            " - 'seo_maturity_level' - 'cif' FROM clients c WHERE id=1"
        ))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert not RETIRED_TABLES & await tables(conn)
        assert not RETIRED_COLUMNS & await columns(conn)
        # vigil_slug llega con un paso posterior, vacío.
        assert await conn.scalar(text("SELECT to_jsonb(c) - 'vigil_slug' FROM clients c WHERE id=1")) == client_before


async def test_fresh_install_reaches_the_same_shape(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert not RETIRED_TABLES & await tables(conn)
        assert not RETIRED_COLUMNS & await columns(conn)


async def test_p12_still_requires_everything_before_the_step(engine):
    await published_previous(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE clients DROP COLUMN ltv"))
        await schema_baseline._verify_schema(conn)  # retirado y ausente: se perdona
        await conn.execute(text("ALTER TABLE clients DROP COLUMN website"))
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            await schema_baseline._verify_schema(conn)


@pytest.mark.parametrize("damage", [
    "CREATE TABLE agency_assets (id SERIAL PRIMARY KEY)",
    "ALTER TABLE clients ADD COLUMN cif VARCHAR(50)",
])
async def test_a_retired_item_coming_back_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError, match="retired"):
            await verify(conn)

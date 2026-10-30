"""El paso del detalle de Search Console es aditivo y su contrato se verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.gsc_detail_schema import MIGRATION, apply, verify
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
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


def test_esta_en_el_plan():
    assert MIGRATION in deployment_schema.MIGRATIONS
    assert MIGRATION.version == "20261022_gsc_detail_v1"


async def test_upgrade_twice_and_ready(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO gsc_daily (site_url, date, clicks, impressions, position) "
            "VALUES ('sc-domain:a.com', '2026-10-01', 5, 50, 3.0)"
        ))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        # Lo publicado sigue ahí; las tablas nuevas empiezan vacías.
        assert await conn.scalar(text("SELECT count(*) FROM gsc_daily")) == 1
        for table in ("gsc_query_daily", "gsc_page_daily", "gsc_detail_sync"):
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


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
    """create_all (tests e init_db) crea lo mismo que la migración (REAL = float4)."""
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)


@pytest.mark.parametrize("damage", [
    "ALTER TABLE gsc_query_daily DROP COLUMN impressions",
    "ALTER TABLE gsc_page_daily ALTER COLUMN position TYPE DOUBLE PRECISION",
    "ALTER TABLE gsc_detail_sync ALTER COLUMN error_code TYPE VARCHAR(10)",
    "ALTER TABLE gsc_query_daily DROP CONSTRAINT gsc_query_daily_pkey",
    "ALTER TABLE gsc_page_daily DROP CONSTRAINT gsc_page_daily_pkey",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

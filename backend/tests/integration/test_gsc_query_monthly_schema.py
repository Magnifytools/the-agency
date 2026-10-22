"""El paso del historial mensual por consulta es aditivo y su contrato se verifica entero."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.gsc_query_monthly_schema import MIGRATION, apply, verify
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
    assert MIGRATION.version == "20261022_gsc_query_monthly_v1"


async def test_upgrade_twice_and_ready(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO gsc_detail_sync (site_url, backfilled_at, last_data_date, query_rows) "
            "VALUES ('sc-domain:a.com', '2026-10-01T06:00:00Z', '2026-10-18', 7)"
        ))
        await conn.execute(text(
            "INSERT INTO gsc_query_daily (site_url, date, query, clicks, impressions, position) "
            "VALUES ('sc-domain:a.com', '2026-10-01', 'q', 1, 10, 3.0)"
        ))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        # Lo publicado sigue ahí; la marca nueva empieza vacía (la próxima pasada importa los meses).
        row = (await conn.execute(text(
            "SELECT query_rows, last_data_date, monthly_backfilled_at FROM gsc_detail_sync"))).one()
        assert row.query_rows == 7 and str(row.last_data_date) == "2026-10-18" and row.monthly_backfilled_at is None
        assert await conn.scalar(text("SELECT count(*) FROM gsc_query_daily")) == 1
        assert await conn.scalar(text("SELECT count(*) FROM gsc_query_monthly")) == 0


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
    """create_all (tests e init_db) crea lo mismo que la migración."""
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)


async def test_el_mes_es_siempre_el_dia_1(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO gsc_query_monthly VALUES ('s', '2026-05-01', 'q', 1, 10, 30.0)"))
    with pytest.raises(Exception):
        async with engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO gsc_query_monthly VALUES ('s', '2026-05-02', 'q', 1, 10, 30.0)"))


@pytest.mark.parametrize("damage", [
    "ALTER TABLE gsc_query_monthly DROP COLUMN weighted_position_sum",
    "ALTER TABLE gsc_query_monthly ALTER COLUMN weighted_position_sum TYPE REAL",
    "ALTER TABLE gsc_query_monthly ALTER COLUMN clicks DROP NOT NULL",
    "ALTER TABLE gsc_query_monthly DROP CONSTRAINT gsc_query_monthly_pkey",
    "ALTER TABLE gsc_query_monthly DROP CONSTRAINT ck_gsc_query_monthly_first_day",
    "ALTER TABLE gsc_detail_sync DROP COLUMN monthly_backfilled_at",
    "ALTER TABLE gsc_detail_sync ALTER COLUMN monthly_backfilled_at TYPE TIMESTAMP",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

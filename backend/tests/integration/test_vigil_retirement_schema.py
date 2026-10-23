"""Retirada de Vigil (3c): vigil_summary y clients.vigil_slug, nada más."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline, vigil_schema
from backend.startup.readiness import check_database_ready
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.vigil_retirement_schema import MIGRATION, RETIRED_COLUMNS, RETIRED_TABLES, verify

pytestmark = pytest.mark.integration


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def tables_and_columns(conn):
    tables = set((await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))).scalars())
    columns = {tuple(r) for r in (await conn.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
    ))).all()}
    return tables, columns


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
            INSERT INTO clients (id,name,contract_type,status,currency,is_internal,is_intermediary_deal,created_at,updated_at,vigil_slug)
            VALUES (1,'Fit Generation','monthly','active','EUR',false,false,'2026-01-01','2026-01-02','fit-generation')
        """))
        await conn.execute(text(
            "INSERT INTO vigil_summary (slug, data, fetched_at) VALUES ('fit-generation', '{}'::jsonb, now())"
        ))


def test_el_contrato_solo_retira_lo_de_vigil():
    assert RETIRED_TABLES == {"vigil_summary"}
    assert RETIRED_COLUMNS == {("clients", "vigil_slug")}
    # La retirada va después del paso que creó lo de Vigil (y de cualquier
    # otro que aún lo leyera); pasos aditivos posteriores no le afectan.
    migrations = deployment_schema.MIGRATIONS
    assert migrations.index(MIGRATION) > migrations.index(vigil_schema.MIGRATION)
    assert vigil_schema.RETIREMENT_VERSION == MIGRATION.version
    assert RETIRED_TABLES <= schema_baseline.RETIRED_TABLES


async def test_subida_con_datos_borra_vigil_y_conserva_el_cliente(engine):
    await published_previous(engine)
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(c) - 'vigil_slug' FROM clients c WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)  # repetir no hace nada
    await deployment_schema.check_deployment_ready(engine)  # vigil_v1 acepta que ya no esté
    await check_database_ready(engine)
    async with engine.begin() as conn:
        tables, columns = await tables_and_columns(conn)
        assert "vigil_summary" not in tables and ("clients", "vigil_slug") not in columns
        assert await conn.scalar(text("SELECT to_jsonb(c) FROM clients c WHERE id=1")) == before
        assert not await conn.scalar(text("SELECT 1 FROM pg_indexes WHERE indexname='uq_clients_vigil_slug'"))
        await MIGRATION.apply(conn)  # idempotente
        await verify(conn)


async def test_instalacion_limpia(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    await check_database_ready(engine)
    async with engine.connect() as conn:
        tables, columns = await tables_and_columns(conn)
        assert "vigil_summary" not in tables and ("clients", "vigil_slug") not in columns


async def test_antes_de_retirar_vigil_v1_sigue_exigiendo_lo_suyo(engine):
    await published_previous(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE clients DROP COLUMN vigil_slug"))
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            await vigil_schema.verify(conn)


async def test_si_vuelve_lo_retirado_se_rechaza(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE clients ADD COLUMN vigil_slug VARCHAR(100)"))
        with pytest.raises(RuntimeError, match="retired columns still present: clients.vigil_slug"):
            await verify(conn)

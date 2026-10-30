"""El interruptor de la vigilancia de cambios es aditivo: todos los clientes quedan apagados."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.web_changes_toggle_schema import MIGRATION, apply, verify

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
        await conn.execute(text("""
            INSERT INTO client_web_settings (client_id, slack_enabled, downtime_to_slack, user_agent)
            VALUES (1, false, true, 'Mozilla/5.0 Chrome/126')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


def test_esta_en_el_plan():
    assert MIGRATION in deployment_schema.MIGRATIONS
    assert MIGRATION.version == "20261023_web_changes_toggle_v1"


async def test_subir_dos_veces_conserva_los_ajustes_y_deja_la_vigilancia_apagada(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(s) - 'updated_at' FROM client_web_settings s WHERE client_id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after = await conn.scalar(text(
            "SELECT to_jsonb(s) - 'updated_at' - 'changes_enabled' FROM client_web_settings s WHERE client_id=1"))
        assert after == before
        assert await conn.scalar(text("SELECT changes_enabled FROM client_web_settings WHERE client_id=1")) is False


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
    "ALTER TABLE client_web_settings ALTER COLUMN changes_enabled DROP NOT NULL",
    "ALTER TABLE client_web_settings ALTER COLUMN changes_enabled DROP DEFAULT",
    "ALTER TABLE client_web_settings DROP COLUMN changes_enabled",
])
async def test_drift_is_rejected(engine, damage):
    async with engine.begin() as conn:
        await apply(conn)
        await conn.execute(text(damage))
    with pytest.raises(RuntimeError, match="Unsupported schema"):
        async with engine.begin() as conn:
            await verify(conn)

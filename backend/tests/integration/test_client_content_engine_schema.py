"""El cliente de Engine es aditivo: los clientes existentes quedan sin enlace."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.client_content_engine_schema import MIGRATION, apply, verify
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
            VALUES (1,'Fit Generation','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


def test_esta_en_el_plan():
    assert MIGRATION in deployment_schema.MIGRATIONS
    assert MIGRATION.version == "20261022_client_content_engine_v1"


async def test_upgrade_twice_keeps_clients_without_link(engine):
    async with engine.begin() as conn:
        # Lo que copiaba el job de The Engine sigue en la BD (fuera del ORM)
        # hasta su paso de retirada: subir no lo toca.
        await conn.execute(text(
            "UPDATE clients SET engine_project_id=7, engine_summary_data='{\"clicks_30d\": 5}' WHERE id=1"
        ))
        before = await conn.scalar(text("SELECT to_jsonb(c) FROM clients c WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after = await conn.scalar(text("SELECT to_jsonb(c) - 'content_engine_client_id' FROM clients c WHERE id=1"))
        assert after == before
        assert await conn.scalar(text("SELECT content_engine_client_id IS NULL FROM clients WHERE id=1")) is True


async def test_sin_las_columnas_de_the_engine_tambien_arranca(engine):
    """Una BD sin las engine_* (como la que crea el ORM) sigue siendo válida."""
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE clients DROP COLUMN engine_summary_data, DROP COLUMN engine_project_id"))
        await conn.execute(text("ALTER TABLE projects DROP COLUMN engine_project_id"))
    await deployment_schema.check_deployment_ready(engine)


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
    "ALTER TABLE clients ALTER COLUMN content_engine_client_id SET DEFAULT ''",
    "ALTER TABLE clients ALTER COLUMN content_engine_client_id TYPE VARCHAR(32)",
    "ALTER TABLE clients ALTER COLUMN content_engine_client_id TYPE TEXT",
    "ALTER TABLE clients DROP COLUMN content_engine_client_id",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

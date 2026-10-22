"""Los términos de marca son aditivos: los clientes existentes quedan con lista vacía."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.client_brand_terms_schema import MIGRATION, apply, verify
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
    assert MIGRATION.version == "20261022_client_brand_terms_v1"


async def test_upgrade_twice_keeps_clients_with_empty_terms(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(c) FROM clients c WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after = await conn.scalar(text("SELECT to_jsonb(c) - 'brand_terms' - 'seo_page_groups' FROM clients c WHERE id=1"))
        assert after == before
        assert await conn.scalar(text("SELECT brand_terms = '[]'::jsonb FROM clients WHERE id=1")) is True


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
    "ALTER TABLE clients ALTER COLUMN brand_terms DROP NOT NULL",
    "ALTER TABLE clients ALTER COLUMN brand_terms DROP DEFAULT",
    "ALTER TABLE clients ALTER COLUMN brand_terms TYPE JSON USING brand_terms::json",
    "ALTER TABLE clients DROP COLUMN brand_terms",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

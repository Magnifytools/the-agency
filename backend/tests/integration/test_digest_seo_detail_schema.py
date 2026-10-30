"""Foto del mes del resumen: tabla nueva, borrada con su resumen."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.digest_seo_detail_schema import MIGRATION, apply, verify
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def clean(engine):
    await reset(engine)
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_subida_y_cascada(engine):
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO clients (id,name,contract_type,status,currency,is_internal,is_intermediary_deal,created_at,updated_at)
            VALUES (1,'Acme','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
        await conn.execute(text("""
            INSERT INTO users (id,email,hashed_password,full_name,role,weekly_hours,is_active,password_reset_required,
                               cost_per_hour,available_hours_month,created_at,updated_at)
            VALUES (1,'a@b.c','x','A','admin',40,true,false,0,147,'2026-01-01','2026-01-01')
        """))
        await conn.execute(text("""
            INSERT INTO weekly_digests (id,client_id,period_start,period_end,status,tone,created_by,created_at,updated_at)
            VALUES (1,1,'2026-09-01','2026-09-30','draft','cercano',1,'2026-10-02','2026-10-02')
        """))
        await conn.execute(text("""
            INSERT INTO digest_seo_details (digest_id, site_url, payload)
            VALUES (1, 'https://acme.es/', '{"status": "ok"}')
        """))
        await conn.execute(text("DELETE FROM weekly_digests WHERE id=1"))
        assert await conn.scalar(text("SELECT count(*) FROM digest_seo_details")) == 0
        await apply(conn)
        await verify(conn)


async def test_instalacion_limpia_y_orm(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)

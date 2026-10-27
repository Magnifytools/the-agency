"""Anotaciones SEO: tabla nueva, borrada con su cliente; la del autor queda a NULL."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.seo_annotations_schema import MIGRATION, apply, verify
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
        await conn.execute(text("INSERT INTO clients (id, name, status) VALUES (1, 'Acme', 'active')"))
        await conn.execute(text("INSERT INTO seo_annotations (client_id, date, text) VALUES (1, '2026-10-05', 'Migración')"))
        with pytest.raises(Exception):
            async with conn.begin_nested():
                await conn.execute(text("INSERT INTO seo_annotations (client_id, date, text) VALUES (1, '2026-10-05', '   ')"))
        await conn.execute(text("DELETE FROM clients WHERE id=1"))
        assert await conn.scalar(text("SELECT count(*) FROM seo_annotations")) == 0
        await apply(conn)
        await verify(conn)


async def test_instalacion_limpia_y_orm(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)

"""Pantallazos de sugerencias: tabla nueva, en cascada con su sugerencia."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.app_suggestion_images_schema import MIGRATION, apply, verify
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


async def test_subida_conserva_las_sugerencias_y_borra_imagenes_en_cascada(engine):
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO app_suggestions (id, text) VALUES (1, 'Con captura')"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.begin() as conn:
        assert await conn.scalar(text("SELECT text FROM app_suggestions WHERE id=1")) == "Con captura"
        await conn.execute(text("""INSERT INTO app_suggestion_images (suggestion_id, name, mime_type, size_bytes, content)
                                   VALUES (1, 'a.png', 'image/png', 3, '\\x010203')"""))
        with pytest.raises(Exception):
            async with conn.begin_nested():
                await conn.execute(text("""INSERT INTO app_suggestion_images (suggestion_id, name, mime_type, size_bytes, content)
                                           VALUES (1, 'a.html', 'text/html', 3, '\\x010203')"""))
        await conn.execute(text("DELETE FROM app_suggestions WHERE id=1"))
        assert await conn.scalar(text("SELECT count(*) FROM app_suggestion_images")) == 0
        await apply(conn)  # idempotente
        await verify(conn)


async def test_instalacion_limpia_y_orm(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)


@pytest.mark.parametrize("damage", [
    "ALTER TABLE app_suggestion_images ALTER COLUMN content DROP NOT NULL",
    "ALTER TABLE app_suggestion_images DROP CONSTRAINT app_suggestion_images_suggestion_id_fkey",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            await verify(conn)

"""El paso de sugerencias es aditivo, trae las del inbox y su contrato se verifica."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.app_suggestions_schema import MIGRATION, verify
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
        await conn.execute(text("""INSERT INTO users
            (id,email,hashed_password,full_name,role,weekly_hours,is_active,password_reset_required,
             cost_per_hour,available_hours_month,created_at,updated_at)
            VALUES (7,'nacho@example.test','hash','Nacho','member',40,true,false,0,147,now(),now())"""))
        await conn.execute(text("""INSERT INTO inbox_notes (user_id, raw_text, source, status, resolved_as, created_at, updated_at)
            VALUES (7, 'Exportar a CSV', 'dashboard', 'processed', 'app_suggestion', '2026-10-01', '2026-10-02'),
                   (7, 'Llamar a Sage', 'dashboard', 'processed', 'task', '2026-10-01', '2026-10-02')"""))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_twice_brings_inbox_suggestions_once(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT author_id, text, done_at FROM app_suggestions"
        ))).all()
    assert rows == [(7, "Exportar a CSV", None)]


async def test_deleting_the_author_keeps_the_suggestion(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM inbox_notes"))
        await conn.execute(text("DELETE FROM users WHERE id=7"))
        assert await conn.scalar(text("SELECT count(*) FROM app_suggestions WHERE author_id IS NULL")) == 1


@pytest.mark.parametrize("damage", [
    "ALTER TABLE app_suggestions ALTER COLUMN page_path TYPE VARCHAR(100)",
    "ALTER TABLE app_suggestions ALTER COLUMN done_at TYPE TIMESTAMP",
    "ALTER TABLE app_suggestions DROP CONSTRAINT app_suggestions_author_id_fkey",
    "ALTER TABLE app_suggestions DROP CONSTRAINT app_suggestions_pkey",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

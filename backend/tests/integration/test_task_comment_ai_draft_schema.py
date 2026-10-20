"""La marca de borrador de IA es aditiva: los comentarios existentes quedan como normales."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Base, User, UserRole
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.task_comment_ai_draft_schema import MIGRATION, verify

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
    async with AsyncSession(engine) as db:
        db.add(User(id=1, email="schema@example.test", hashed_password="x", full_name="Schema", role=UserRole.admin))
        await db.commit()
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO tasks (id,title,status,priority,is_inbox,is_recurring,created_at,updated_at)
            VALUES (1,'Tarea','pending','medium',false,false,'2026-01-01','2026-01-02')
        """))
        await conn.execute(text("""
            INSERT INTO task_comments (id,task_id,user_id,text,created_at,updated_at)
            VALUES (1,1,1,'Comentario antiguo','2026-01-01','2026-01-02')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_twice_keeps_comments_as_normal(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(c) FROM task_comments c WHERE id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after = await conn.scalar(text("SELECT to_jsonb(c) - 'is_ai_draft' FROM task_comments c WHERE id=1"))
        assert after == before
        assert await conn.scalar(text("SELECT is_ai_draft FROM task_comments WHERE id=1")) is False


@pytest.mark.parametrize("damage", [
    "ALTER TABLE task_comments ALTER COLUMN is_ai_draft DROP NOT NULL",
    "ALTER TABLE task_comments ALTER COLUMN is_ai_draft DROP DEFAULT",
    "ALTER TABLE task_comments DROP COLUMN is_ai_draft",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

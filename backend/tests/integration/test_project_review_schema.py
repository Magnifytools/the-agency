"""Rehearse opt-in review on the published P21 schema with history intact."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Base, Client, User, UserRole
from backend.startup import deployment_schema, schema_baseline
from backend.startup.project_review_schema import MIGRATION, apply
from backend.startup.schema_runner import run_schema_migrations


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def published_p21(engine):
    await reset(engine)
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    async with AsyncSession(engine) as db:
        db.add(User(id=1, email="review-schema@example.test", full_name="Schema", hashed_password="x", role=UserRole.admin))
        db.add(Client(id=1, name="Existing client"))
        await db.commit()
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO projects(id,name,client_id,status,progress_percent,is_recurring,
                created_at,updated_at,owner_id)
            VALUES (1,'Existing project',1,'active',0,false,'2026-01-01','2026-01-02',NULL)
        """))
        await conn.execute(text("""
            INSERT INTO tasks(id,title,project_id,client_id,status,priority,is_inbox,is_recurring,
                created_at,updated_at,completed_at,assigned_to)
            VALUES (1,'Historical completion',1,1,'completed','medium',false,false,
                '2026-01-01','2026-01-02',NULL,NULL)
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_is_opt_in_preserves_business_values_and_ledger(engine):
    async with engine.connect() as conn:
        project = await conn.scalar(text("SELECT to_jsonb(p) FROM projects p WHERE id=1"))
        task = await conn.scalar(text("SELECT to_jsonb(t) FROM tasks t WHERE id=1"))
        ledger = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT to_jsonb(p)-'requires_task_review' FROM projects p WHERE id=1")) == project
        assert await conn.scalar(text("SELECT requires_task_review FROM projects WHERE id=1")) is False
        assert await conn.scalar(text("SELECT to_jsonb(t) FROM tasks t WHERE id=1")) == task
        after = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
        assert set(ledger) <= set(after)
        assert len(after) == len(ledger) + 1


@pytest.mark.parametrize("damage", ["nullable", "default", "type"])
async def test_drift_rejected_without_stamp_or_silent_repair(engine, damage):
    async with engine.begin() as conn:
        await apply(conn)
        statements = {
            "nullable": "ALTER TABLE projects ALTER COLUMN requires_task_review DROP NOT NULL",
            "default": "ALTER TABLE projects ALTER COLUMN requires_task_review SET DEFAULT true",
            "type": "ALTER TABLE projects DROP COLUMN requires_task_review, ADD COLUMN requires_task_review text NOT NULL DEFAULT 'false'",
        }
        await conn.execute(text(statements[damage]))
    with pytest.raises(RuntimeError, match="projects.requires_task_review"):
        await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions WHERE version=:version"), {"version": MIGRATION.version}) == 0

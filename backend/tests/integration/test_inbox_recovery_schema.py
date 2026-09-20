"""Upgrade the actual published P14 contract, preserving captured work."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Base, User, UserRole
from backend.startup import deployment_schema, schema_baseline
from backend.startup.inbox_recovery_schema import apply
from backend.startup.job_runtime_schema import MIGRATION as JOB_RUNTIME_MIGRATION
from backend.startup.schema_runner import run_schema_migrations


async def _empty(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def published_schema(engine):
    await _empty(engine)
    await run_schema_migrations(
        engine, (*schema_baseline.MIGRATIONS, JOB_RUNTIME_MIGRATION), schema_baseline.preflight,
    )
    yield
    await _empty(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_p14_upgrade_preserves_notes_and_ledger_without_reclassifying(engine):
    async with AsyncSession(engine) as db:
        actor = User(email="migration@example.test", full_name="Migration", hashed_password="synthetic", role=UserRole.admin)
        db.add(actor)
        await db.flush()
        for status in ("pending", "classified", "processed", "dismissed"):
            await db.execute(text("""
                INSERT INTO inbox_notes (user_id,raw_text,source,status,ai_suggestion,created_at,updated_at)
                VALUES (:user_id,:raw_text,'chrome_extension',CAST(:status AS inboxnotestatus),
                        '{"legacy":"preserved"}', '2026-01-01', '2026-01-02')
            """), {"user_id": actor.id, "status": status, "raw_text": status})
        await db.commit()
    async with engine.connect() as conn:
        before = (await conn.execute(text("SELECT id,raw_text,source,status,ai_suggestion,created_at,updated_at FROM inbox_notes ORDER BY id"))).all()
        ledger = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT id,raw_text,source,status,ai_suggestion,created_at,updated_at FROM inbox_notes ORDER BY id"))).all() == before
        assert (await conn.execute(text("SELECT classification_error_code,classification_next_attempt_at FROM inbox_notes"))).all() == [(None, None)] * 4
        after = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
        assert len(after) == len(ledger) + 1
        assert set(ledger) <= set(after)


@pytest.mark.parametrize("damage", ["length", "timezone", "nullable", "index"])
async def test_incompatible_retry_state_rolls_back_without_ledger(engine, damage):
    async with engine.begin() as conn:
        await apply(conn)
        if damage == "length":
            await conn.execute(text("ALTER TABLE inbox_notes ALTER COLUMN classification_error_code TYPE varchar(16)"))
        elif damage == "timezone":
            await conn.execute(text("DROP INDEX ix_inbox_pending_attempt"))
            await conn.execute(text("ALTER TABLE inbox_notes ALTER COLUMN classification_next_attempt_at TYPE timestamptz"))
        elif damage == "nullable":
            await conn.execute(text("ALTER TABLE inbox_notes ALTER COLUMN classification_error_code SET NOT NULL"))
        else:
            await conn.execute(text("DROP INDEX ix_inbox_pending_attempt"))
            await conn.execute(text("CREATE INDEX ix_inbox_pending_attempt ON inbox_notes (updated_at,id) WHERE status='classified'"))
    with pytest.raises(RuntimeError, match="inbox_notes"):
        await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions")) == 3


async def test_post_publication_drift_fails_readiness_without_repair(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE inbox_notes DROP COLUMN classification_next_attempt_at"))
    with pytest.raises(RuntimeError, match="inbox_notes.classification_next_attempt_at"):
        await deployment_schema.check_deployment_ready(engine)
    with pytest.raises(RuntimeError, match="inbox_notes.classification_next_attempt_at"):
        await deployment_schema.migrate_schema(engine)

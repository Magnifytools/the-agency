"""Current release upgrades the published baseline without changing its ledger."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline


async def _empty(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def isolated_schema(engine):
    await _empty(engine)
    await schema_baseline.migrate_schema(engine)
    yield
    await _empty(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_preserves_published_history_and_repeats(engine):
    async with engine.begin() as conn:
        before = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
        await conn.execute(text("CREATE TABLE preserved_external_table (value TEXT)"))
        await conn.execute(text("INSERT INTO preserved_external_table VALUES ('preserved')"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        after = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
        assert {tuple(row) for row in before} <= {tuple(row) for row in after}
        assert len(after) == len(before) + 2
        assert await conn.scalar(text("SELECT count(*) FROM job_runtime")) == 0
        assert await conn.scalar(text("SELECT value FROM preserved_external_table")) == "preserved"


async def test_empty_database_runs_all_steps(engine):
    await _empty(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions")) == 4
        assert await conn.scalar(text("SELECT to_regclass('public.tasks') IS NOT NULL")) is True


@pytest.mark.parametrize("damage", ["type", "nullable", "primary_key"])
async def test_incompatible_job_table_blocks_without_adoption(engine, damage):
    from backend.startup.job_runtime_schema import apply
    async with engine.begin() as conn:
        await apply(conn)
        if damage == "type":
            await conn.execute(text("ALTER TABLE job_runtime ALTER COLUMN started_at TYPE timestamp"))
        elif damage == "nullable":
            await conn.execute(text("ALTER TABLE job_runtime ALTER COLUMN success_at SET NOT NULL"))
        else:
            await conn.execute(text("ALTER TABLE job_runtime DROP CONSTRAINT job_runtime_pkey"))
    with pytest.raises(RuntimeError, match="job_runtime"):
        await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions")) == 2


async def test_post_upgrade_schema_drift_rejected_without_repair(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE job_runtime ALTER COLUMN error_code TYPE varchar(32)"))
    with pytest.raises(RuntimeError, match="job_runtime.error_code"):
        await deployment_schema.check_deployment_ready(engine)
    with pytest.raises(RuntimeError, match="job_runtime.error_code"):
        await deployment_schema.migrate_schema(engine)

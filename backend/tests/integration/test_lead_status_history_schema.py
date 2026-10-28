"""Historial de etapas del Pipeline: cada lead existente arranca con su etapa actual."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.lead_status_history_schema import MIGRATION
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
            INSERT INTO leads (id, company_name, status, source, currency, created_at, updated_at) VALUES
              (1, 'Acme', 'proposal', 'website', 'EUR', '2026-01-01', '2026-03-01'),
              (2, 'Beta', 'new', 'other', 'EUR', '2026-02-01', '2026-02-01')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_la_subida_dos_veces_deja_una_fila_por_lead(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT lead_id, status::text, entered_at::date::text FROM lead_status_history ORDER BY lead_id"))).all()
        assert [tuple(r) for r in rows] == [(1, "proposal", "2026-03-01"), (2, "new", "2026-02-01")]
        await conn.execute(text("DELETE FROM leads WHERE id = 1"))
        assert await conn.scalar(text("SELECT count(*) FROM lead_status_history")) == 1

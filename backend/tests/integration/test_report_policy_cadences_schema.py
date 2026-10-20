"""Las dos cadencias son aditivas: cada política conserva justo la que tenía."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Base, Client, ClientStatus
from backend.startup import deployment_schema, schema_baseline
from backend.startup.report_policy_cadences_schema import MIGRATION, verify
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration

# (enabled, cadence) antiguos -> (weekly_enabled, monthly_enabled)
LEGACY = {
    1: ((False, "weekly"), (False, False)),
    2: ((True, "weekly"), (True, False)),
    3: ((True, "monthly"), (False, True)),
    4: ((False, "monthly"), (False, False)),
}


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
        db.add_all([Client(id=client_id, name=f"Cliente {client_id}", status=ClientStatus.active) for client_id in LEGACY])
        await db.commit()
    async with engine.begin() as conn:
        # Esquema antiguo: sólo enabled/cadence. SQL crudo, el ORM ya no lo conoce.
        for client_id, ((enabled, cadence), _) in LEGACY.items():
            await conn.execute(text("""
                INSERT INTO client_report_policies (client_id, enabled, cadence, revision, created_at, updated_at)
                VALUES (:id, :enabled, :cadence, 3, '2026-01-01', '2026-01-02')
            """), {"id": client_id, "enabled": enabled, "cadence": cadence})
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def flags(conn):
    rows = await conn.execute(text(
        "SELECT client_id, weekly_enabled, monthly_enabled, enabled, cadence, revision FROM client_report_policies"
    ))
    return {row.client_id: row for row in rows}


async def test_backfill_keeps_each_policy_cadence_and_is_idempotent(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        rows = await flags(conn)
    for client_id, ((enabled, cadence), expected) in LEGACY.items():
        row = rows[client_id]
        assert (row.weekly_enabled, row.monthly_enabled) == expected
        # Las columnas antiguas y la revisión no se tocan.
        assert (row.enabled, row.cadence, row.revision) == (enabled, cadence, 3)

    # Un cambio posterior (ambas cadencias) no se pisa al volver a aplicar el
    # paso ni al volver a migrar.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE client_report_policies SET weekly_enabled = true WHERE client_id = 3"))
        await MIGRATION.apply(conn)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert (await flags(conn))[3].weekly_enabled is True
        await verify(conn)


@pytest.mark.parametrize("damage", [
    "ALTER TABLE client_report_policies ALTER COLUMN weekly_enabled DROP NOT NULL",
    "ALTER TABLE client_report_policies ALTER COLUMN monthly_enabled DROP DEFAULT",
    "ALTER TABLE client_report_policies DROP COLUMN monthly_enabled",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text(damage))
        with pytest.raises(RuntimeError):
            await verify(conn)

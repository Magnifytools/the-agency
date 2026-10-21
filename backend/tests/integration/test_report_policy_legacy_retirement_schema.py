"""Retirada de client_report_policies.enabled/cadence: sólo esas dos columnas."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Base, Client, ClientReportPolicy, ClientStatus
from backend.startup import deployment_schema, schema_baseline
from backend.startup.readiness import check_database_ready
from backend.startup.report_policy_legacy_retirement_schema import (
    MIGRATION, RETIRED_COLUMNS, RETIRED_TABLES, verify,
)
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration

LEGACY = {("client_report_policies", "enabled"), ("client_report_policies", "cadence")}

# client_id -> (enabled, cadence, weekly_enabled, monthly_enabled)
POLICIES = {
    1: (True, "weekly", True, False),
    2: (True, "monthly", False, True),
    3: (True, "weekly", True, True),  # las dos, ya con el esquema nuevo
    4: (False, "weekly", False, False),
}


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def columns(conn):
    return {tuple(r) for r in (await conn.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
    ))).all()}


async def policies(conn):
    return {
        row["client_id"]: row["policy"]
        for row in (await conn.execute(text(
            "SELECT client_id, to_jsonb(p) - 'enabled' - 'cadence' AS policy"
            " FROM client_report_policies p"
        ))).mappings()
    }


@pytest_asyncio.fixture(autouse=True)
async def clean(engine):
    await reset(engine)
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def published_previous(engine):
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    async with AsyncSession(engine) as db:
        db.add_all([Client(id=i, name=f"Cliente {i}", status=ClientStatus.active) for i in POLICIES])
        await db.commit()
    async with engine.begin() as conn:
        # SQL crudo: el ORM ya no conoce enabled/cadence.
        for client_id, (enabled, cadence, weekly, monthly) in POLICIES.items():
            await conn.execute(text("""
                INSERT INTO client_report_policies
                    (client_id, enabled, cadence, weekly_enabled, monthly_enabled, revision, created_at, updated_at)
                VALUES (:id, :enabled, :cadence, :weekly, :monthly, 7, '2026-01-01', '2026-01-02')
            """), {"id": client_id, "enabled": enabled, "cadence": cadence, "weekly": weekly, "monthly": monthly})


def test_contract_only_retires_the_two_legacy_columns():
    assert RETIRED_TABLES == frozenset()
    assert RETIRED_COLUMNS == LEGACY
    assert MIGRATION in deployment_schema.MIGRATIONS
    assert LEGACY <= schema_baseline.RETIRED_COLUMNS


async def test_upgrade_drops_legacy_columns_and_keeps_every_policy(engine):
    await published_previous(engine)
    async with engine.connect() as conn:
        assert LEGACY <= await columns(conn)
        before = await policies(conn)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)  # repetir no hace nada
    await deployment_schema.check_deployment_ready(engine)
    await check_database_ready(engine)
    async with engine.begin() as conn:
        assert not LEGACY & await columns(conn)
        assert await policies(conn) == before
        for client_id, (_, _, weekly, monthly) in POLICIES.items():
            assert (before[client_id]["weekly_enabled"], before[client_id]["monthly_enabled"]) == (weekly, monthly)
        await MIGRATION.apply(conn)  # idempotente
        await verify(conn)


async def test_fresh_install_reaches_the_same_shape_and_orm_writes(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    await check_database_ready(engine)
    async with engine.connect() as conn:
        assert not LEGACY & await columns(conn)
    async with AsyncSession(engine) as db:
        db.add(Client(id=1, name="Cliente", status=ClientStatus.active))
        await db.flush()
        db.add(ClientReportPolicy(client_id=1, monthly_enabled=True))
        await db.commit()
        policy = await db.get(ClientReportPolicy, 1)
        assert (policy.weekly_enabled, policy.monthly_enabled, policy.revision) == (False, True, 1)


async def test_p12_still_requires_everything_before_the_step(engine):
    await published_previous(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE client_report_policies DROP COLUMN cadence"))
        await schema_baseline._verify_schema(conn)  # retirada y ausente: se perdona
        await conn.execute(text("ALTER TABLE client_report_policies DROP COLUMN revision"))
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            await schema_baseline._verify_schema(conn)


async def test_a_retired_column_coming_back_is_rejected(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE client_report_policies ADD COLUMN enabled BOOLEAN"))
        with pytest.raises(RuntimeError, match="retired columns still present: client_report_policies.enabled"):
            await verify(conn)

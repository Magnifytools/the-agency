"""Retirada de alert_settings.notify_in_app/notify_email: sólo esas dos columnas."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import AlertSettings, Base, User, UserRole
from backend.startup import deployment_schema, schema_baseline
from backend.startup.alert_settings_notify_retirement_schema import (
    MIGRATION, RETIRED_COLUMNS, RETIRED_TABLES, verify,
)
from backend.startup.readiness import check_database_ready
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration

LEGACY = {("alert_settings", "notify_in_app"), ("alert_settings", "notify_email")}

# user_id -> (days_without_activity, days_before_deadline, days_without_contact, max_tasks_per_week, in_app, email)
SETTINGS = {
    1: (14, 3, 10, 15, True, False),
    2: (7, 5, 20, 30, False, True),
}


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def columns(conn):
    return {tuple(r) for r in (await conn.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
    ))).all()}


async def thresholds(conn):
    return {
        row["user_id"]: row["settings"]
        for row in (await conn.execute(text(
            "SELECT user_id, to_jsonb(s) - 'notify_in_app' - 'notify_email' AS settings"
            " FROM alert_settings s"
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
    async with engine.begin() as conn:
        for user_id in SETTINGS:
            await conn.execute(text("""
                INSERT INTO users (id,email,hashed_password,full_name,role,weekly_hours,is_active,
                                   password_reset_required,created_at,updated_at)
                VALUES (:id,:email,'x',:name,'member',40,true,false,'2026-01-01','2026-01-02')
            """), {"id": user_id, "email": f"u{user_id}@example.com", "name": f"Usuario {user_id}"})
        # SQL crudo: el ORM ya no conoce notify_in_app/notify_email.
        for user_id, (activity, deadline, contact, tasks, in_app, email) in SETTINGS.items():
            await conn.execute(text("""
                INSERT INTO alert_settings
                    (user_id, days_without_activity, days_before_deadline, days_without_contact,
                     max_tasks_per_week, notify_in_app, notify_email, created_at, updated_at)
                VALUES (:id, :activity, :deadline, :contact, :tasks, :in_app, :email, '2026-01-01', '2026-01-02')
            """), {"id": user_id, "activity": activity, "deadline": deadline, "contact": contact,
                   "tasks": tasks, "in_app": in_app, "email": email})


def test_contract_only_retires_the_two_notify_columns():
    assert RETIRED_TABLES == frozenset()
    assert RETIRED_COLUMNS == LEGACY
    assert MIGRATION in deployment_schema.MIGRATIONS
    assert LEGACY <= schema_baseline.RETIRED_COLUMNS


async def test_upgrade_drops_notify_columns_and_keeps_every_threshold(engine):
    await published_previous(engine)
    async with engine.connect() as conn:
        assert LEGACY <= await columns(conn)
        before = await thresholds(conn)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)  # repetir no hace nada
    await deployment_schema.check_deployment_ready(engine)
    await check_database_ready(engine)
    async with engine.begin() as conn:
        assert not LEGACY & await columns(conn)
        assert await thresholds(conn) == before
        for user_id, (activity, deadline, contact, tasks, _, _) in SETTINGS.items():
            row = before[user_id]
            assert (row["days_without_activity"], row["days_before_deadline"],
                    row["days_without_contact"], row["max_tasks_per_week"]) == (activity, deadline, contact, tasks)
        await MIGRATION.apply(conn)  # idempotente
        await verify(conn)


async def test_fresh_install_reaches_the_same_shape_and_orm_writes(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    await check_database_ready(engine)
    async with engine.connect() as conn:
        assert not LEGACY & await columns(conn)
    async with AsyncSession(engine) as db:
        db.add(User(id=1, email="u@example.com", hashed_password="x", full_name="U", role=UserRole.member))
        await db.flush()
        db.add(AlertSettings(user_id=1, max_tasks_per_week=20))
        await db.commit()
        settings = (await db.execute(text(
            "SELECT days_without_activity, max_tasks_per_week FROM alert_settings WHERE user_id=1"
        ))).one()
        assert tuple(settings) == (14, 20)


async def test_p12_still_requires_everything_before_the_step(engine):
    await published_previous(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE alert_settings DROP COLUMN notify_email"))
        await schema_baseline._verify_schema(conn)  # retirada y ausente: se perdona
        await conn.execute(text("ALTER TABLE alert_settings DROP COLUMN max_tasks_per_week"))
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            await schema_baseline._verify_schema(conn)


async def test_a_retired_column_coming_back_is_rejected(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE alert_settings ADD COLUMN notify_email BOOLEAN"))
        with pytest.raises(RuntimeError, match="retired columns still present: alert_settings.notify_email"):
            await verify(conn)

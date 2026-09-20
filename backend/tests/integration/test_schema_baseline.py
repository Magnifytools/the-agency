"""PostgreSQL contract tests for adopting the frozen P12 schema baseline."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.db.models import Base
from backend.startup.schema_baseline import (
    BASELINE_CHECKSUM,
    EXPECTED_SCHEMA_VERSION,
    MIGRATIONS,
    check_deployment_ready,
    migrate_schema,
)


async def _empty_public_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


async def _restore_model_schema(engine) -> None:
    await _empty_public_schema(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _ledger_rows(engine):
    async with engine.connect() as conn:
        exists = await conn.scalar(text("SELECT to_regclass('public.agency_schema_versions') IS NOT NULL"))
        if not exists:
            return []
        return (await conn.execute(text(
            "SELECT version,checksum FROM agency_schema_versions ORDER BY version"
        ))).all()


@pytest_asyncio.fixture(autouse=True)
async def isolated_public_schema(engine):
    """This file owns its exclusive database and restores the normal test shape."""
    await _restore_model_schema(engine)
    try:
        yield
    finally:
        await _restore_model_schema(engine)
        # Restore the shared harness contract for tests in later modules. The
        # setup intentionally starts from bare metadata to test real upgrades.
        async with engine.begin() as conn:
            await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_current_model_schema_adopts_once_and_is_ready(engine):
    await migrate_schema(engine)
    first = await _ledger_rows(engine)
    await migrate_schema(engine)

    assert await _ledger_rows(engine) == first == sorted(
        (migration.version, BASELINE_CHECKSUM) for migration in MIGRATIONS
    )
    await check_deployment_ready(engine)


async def test_empty_database_bootstraps_then_repeats_without_extra_history(engine):
    await _empty_public_schema(engine)

    await migrate_schema(engine)
    await check_deployment_ready(engine)
    first = await _ledger_rows(engine)
    await migrate_schema(engine)

    assert await _ledger_rows(engine) == first
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 70
        assert await conn.scalar(text("SELECT to_regclass('public.tasks') IS NOT NULL")) is True


async def test_supported_legacy_shape_upgrades_without_rewriting_sentinels(engine):
    sentinel = "baseline-preserves-this-text"
    async with engine.begin() as conn:
        await conn.execute(text("""INSERT INTO users
            (id,email,hashed_password,full_name,role,weekly_hours,is_active,password_reset_required,
             cost_per_hour,available_hours_month,created_at,updated_at)
            VALUES (91001,'baseline@example.test','hash',:sentinel,'admin',40,true,false,0,147,now(),now())"""),
            {"sentinel": sentinel})
        await conn.execute(text("""INSERT INTO clients
            (id,name,contract_type,status,currency,is_internal,is_intermediary_deal,created_at,updated_at)
            VALUES (91001,:sentinel,'monthly','active','EUR',false,false,now(),now())"""),
            {"sentinel": sentinel})
        await conn.execute(text("""INSERT INTO projects
            (id,name,client_id,status,progress_percent,is_recurring,created_at,updated_at)
            VALUES (91001,:sentinel,91001,'active',0,false,now(),now())"""), {"sentinel": sentinel})
        await conn.execute(text("""INSERT INTO tasks
            (id,title,status,priority,is_inbox,is_recurring,created_at,updated_at)
            VALUES (91001,:sentinel,'pending','medium',false,false,now(),now())"""), {"sentinel": sentinel})
        await conn.execute(text("""INSERT INTO notifications
            (id,user_id,type,title,is_read,created_at,updated_at)
            VALUES (91001,91001,'legacy',:sentinel,false,now(),now())"""), {"sentinel": sentinel})
        await conn.execute(text("""INSERT INTO daily_updates
            (id,user_id,date,raw_text,status,created_at,updated_at)
            VALUES (91001,91001,'2026-09-20',:sentinel,'draft',now(),now())"""), {"sentinel": sentinel})

        # A reviewed predecessor: core tables exist, while additive P1-P11
        # columns and independently introduced tables do not yet exist.
        for table in (
            "task_recurrence_occurrences", "digest_external_delivery_events",
            "communication_occurrences", "delivery_attempts", "deliveries",
            "communication_requests", "communication_schedules",
            "client_report_policies", "command_receipts", "change_logs",
            "project_evidence",
        ):
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
        for table, columns in {
            "projects": ["owner_id"],
            "tasks": ["completed_at", "recurrence_anchor_date", "recurrence_paused_at", "recurrence_occurrence_date"],
            "daily_updates": ["revision", "source_facts"],
            "notifications": [
                "incident_state", "incident_severity", "incident_revision",
                "incident_detected_at", "incident_fingerprint", "incident_snoozed_until",
                "incident_resolved_at", "incident_resolution_reason",
                "incident_dismissal_reason", "entity_key",
            ],
        }.items():
            for column in columns:
                await conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}" CASCADE'))

    await migrate_schema(engine)
    await check_deployment_ready(engine)

    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT full_name FROM users WHERE id=91001")) == sentinel
        assert await conn.scalar(text("SELECT name FROM clients WHERE id=91001")) == sentinel
        assert await conn.scalar(text("SELECT name FROM projects WHERE id=91001")) == sentinel
        assert await conn.scalar(text("SELECT title FROM tasks WHERE id=91001")) == sentinel
        assert await conn.scalar(text("SELECT title FROM notifications WHERE id=91001")) == sentinel
        assert await conn.scalar(text("SELECT raw_text FROM daily_updates WHERE id=91001")) == sentinel
        assert await conn.scalar(text("SELECT incident_state FROM notifications WHERE id=91001")) is None
        assert await conn.scalar(text("SELECT source_facts FROM daily_updates WHERE id=91001")) == []
        assert await conn.scalar(text("SELECT completed_at FROM tasks WHERE id=91001")) is None


@pytest.mark.parametrize(
    "damage",
    ["type", "numeric_type", "varchar_length", "foreign_key", "primary_key", "alembic"],
)
async def test_unsupported_shape_is_rejected_before_ledger(engine, damage):
    async with engine.begin() as conn:
        if damage == "type":
            await conn.execute(text("ALTER TABLE tasks ALTER COLUMN completed_at TYPE TEXT"))
        elif damage == "numeric_type":
            await conn.execute(text("""ALTER TABLE projects ALTER COLUMN budget_amount
                TYPE DOUBLE PRECISION USING budget_amount::double precision"""))
        elif damage == "varchar_length":
            await conn.execute(text("ALTER TABLE tasks ALTER COLUMN title TYPE VARCHAR(254)"))
        elif damage == "foreign_key":
            fk = await conn.scalar(text("""SELECT conname FROM pg_constraint
                WHERE conrelid='projects'::regclass AND contype='f'
                  AND conkey=ARRAY[(SELECT attnum FROM pg_attribute
                      WHERE attrelid='projects'::regclass AND attname='owner_id')]::smallint[]"""))
            await conn.execute(text(f'ALTER TABLE projects DROP CONSTRAINT "{fk}"'))
        elif damage == "primary_key":
            await conn.execute(text("ALTER TABLE notifications DROP CONSTRAINT notifications_pkey CASCADE"))
        else:
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))

    with pytest.raises((RuntimeError, DBAPIError)):
        await migrate_schema(engine)
    assert await _ledger_rows(engine) == []


async def test_post_ledger_drift_blocks_without_silent_repair(engine):
    await migrate_schema(engine)
    before = await _ledger_rows(engine)
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE tasks ALTER COLUMN completed_at TYPE TEXT"))

    with pytest.raises(RuntimeError, match="type of tasks.completed_at"):
        await migrate_schema(engine)

    assert await _ledger_rows(engine) == before
    async with engine.connect() as conn:
        assert await conn.scalar(text("""SELECT udt_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='tasks' AND column_name='completed_at'""")) == "text"


async def test_legacy_duplicate_active_timers_fail_without_deleting_or_marking_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text("""INSERT INTO users
            (id,email,hashed_password,full_name,role,weekly_hours,is_active,password_reset_required,
             cost_per_hour,available_hours_month,created_at,updated_at)
            VALUES (92001,'timer-baseline@example.test','hash','Timer baseline','admin',40,true,false,0,147,now(),now())"""))
        await conn.execute(text("""INSERT INTO time_entries
            (id,user_id,minutes,started_at,accumulated_seconds,date,created_at,updated_at) VALUES
            (92001,92001,NULL,now(),0,now(),now(),now()),
            (92002,92001,NULL,now(),0,now(),now(),now())"""))

    with pytest.raises(DBAPIError):
        await migrate_schema(engine)

    async with engine.connect() as conn:
        assert await conn.scalar(text(
            "SELECT count(*) FROM time_entries WHERE user_id=92001 AND minutes IS NULL"
        )) == 2
        rows = await _ledger_rows(engine)
        assert EXPECTED_SCHEMA_VERSION not in {row.version for row in rows}
        assert await conn.scalar(text("""SELECT count(*) FROM pg_indexes
            WHERE schemaname='public' AND tablename='time_entries'
              AND indexdef LIKE 'CREATE UNIQUE INDEX%WHERE (minutes IS NULL)'""")) == 0


async def test_known_production_variants_are_adopted_without_conversion(engine):
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE proposals ALTER COLUMN valid_until TYPE TIMESTAMP WITHOUT TIME ZONE USING valid_until::timestamp"))
        for table, column in (
            ("financial_settings", "credit_alert_pct"),
            ("financial_settings", "tax_reserve_target_pct"),
            ("financial_settings", "default_vat_rate"),
            ("financial_settings", "corporate_tax_rate"),
            ("financial_settings", "irpf_retention_rate"),
            ("financial_settings", "advisor_expense_alert_pct"),
            ("financial_settings", "advisor_margin_warning_pct"),
            ("income", "vat_rate"), ("expenses", "vat_rate"), ("taxes", "tax_rate"),
        ):
            await conn.execute(text(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE DOUBLE PRECISION USING "{column}"::double precision'
            ))
        await conn.execute(text("ALTER TABLE users ALTER COLUMN morning_reminder_time DROP NOT NULL"))
        await conn.execute(text("ALTER TABLE users ALTER COLUMN morning_reminder_time SET DEFAULT '09:00'"))

    await migrate_schema(engine)
    await migrate_schema(engine)
    await check_deployment_ready(engine)

    async with engine.connect() as conn:
        variants = (await conn.execute(text("""SELECT table_name,column_name,udt_name
            FROM information_schema.columns WHERE table_schema='public' AND (
              (table_name='proposals' AND column_name='valid_until') OR
              (table_name='financial_settings' AND column_name='credit_alert_pct'))
            ORDER BY table_name,column_name"""))).all()
        assert variants == [
            ("financial_settings", "credit_alert_pct", "float8"),
            ("proposals", "valid_until", "timestamp"),
        ]
        reminder = (await conn.execute(text("""SELECT is_nullable,column_default
            FROM information_schema.columns WHERE table_schema='public'
              AND table_name='users' AND column_name='morning_reminder_time'"""))).one()
        assert reminder.is_nullable == "YES"
        assert "09:00" in reminder.column_default

"""Rehearse upgrade from P20 and reject receipts that cannot enforce recovery."""
import json

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Base, Client, User, UserRole
from backend.startup import deployment_schema, schema_baseline
from backend.startup.client_onboarding_schema import MIGRATION, apply, verify
from backend.startup.schema_runner import run_schema_migrations


async def reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture(autouse=True)
async def p20_schema(engine):
    await reset(engine)
    preceding = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, preceding, schema_baseline.preflight)
    async with AsyncSession(engine) as db:
        db.add_all([
            User(id=1, email="schema1@example.test", hashed_password="synthetic", full_name="One", role=UserRole.admin),
            User(id=2, email="schema2@example.test", hashed_password="synthetic", full_name="Two", role=UserRole.admin),
            Client(id=1, name="Historical client"),
        ])
        await db.commit()
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_upgrade_preserves_history_and_ledger_and_is_repeatable(engine):
    async with engine.connect() as conn:
        clients = (await conn.execute(text("SELECT to_jsonb(c) FROM clients c"))).scalars().all()
        ledger = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT to_jsonb(c) FROM clients c"))).scalars().all() == clients
        after = (await conn.execute(text("SELECT * FROM agency_schema_versions ORDER BY version"))).all()
        assert set(ledger) <= set(after)
        assert len(after) == len(deployment_schema.MIGRATIONS)
        assert await conn.scalar(text("SELECT count(*) FROM client_onboarding_receipts")) == 0


@pytest.mark.parametrize("damage", ["length", "default", "pk", "check", "unvalidated", "user_fk", "journal_fk"])
async def test_incompatible_receipts_fail_readiness_and_do_not_record_migration(engine, damage):
    async with engine.begin() as conn:
        await apply(conn)
        if damage == "length":
            await conn.execute(text("ALTER TABLE client_onboarding_receipts ALTER COLUMN request_hash TYPE varchar(32)"))
        elif damage == "default":
            await conn.execute(text("ALTER TABLE client_onboarding_receipts ALTER COLUMN status SET DEFAULT 'cancelled'"))
        elif damage == "pk":
            await conn.execute(text("ALTER TABLE client_onboarding_receipts DROP CONSTRAINT client_onboarding_receipts_pkey"))
            await conn.execute(text("ALTER TABLE client_onboarding_receipts ADD PRIMARY KEY (request_key)"))
        elif damage in {"check", "unvalidated"}:
            await conn.execute(text("ALTER TABLE client_onboarding_receipts DROP CONSTRAINT ck_client_onboarding_receipts_key"))
            expr = "request_key ~ '^[A-Za-z0-9_-]{16,64}$'" if damage == "unvalidated" else "length(request_key)>0"
            suffix = " NOT VALID" if damage == "unvalidated" else ""
            await conn.execute(text(f"ALTER TABLE client_onboarding_receipts ADD CONSTRAINT ck_client_onboarding_receipts_key CHECK ({expr}){suffix}"))
        else:
            column = "user_id" if damage == "user_fk" else "change_log_id"
            table = "users" if damage == "user_fk" else "change_logs"
            await conn.execute(text(f"ALTER TABLE client_onboarding_receipts DROP CONSTRAINT client_onboarding_receipts_{column}_fkey"))
            await conn.execute(text(f"ALTER TABLE client_onboarding_receipts ADD FOREIGN KEY ({column}) REFERENCES {table}(id)"))
    with pytest.raises(RuntimeError, match="client_onboarding_receipts"):
        await deployment_schema.migrate_schema(engine)
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions WHERE version=:version"), {"version": MIGRATION.version}) == 0


async def test_cancelled_receipt_is_per_user_terminal_and_has_sql_null_payload(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO client_onboarding_receipts (user_id,request_key,status)
            VALUES (1,'shared-request-key','cancelled'), (2,'shared-request-key','cancelled')
        """))
        assert await conn.scalar(text("SELECT count(*) FROM client_onboarding_receipts WHERE result IS NULL AND request_hash IS NULL AND change_log_id IS NULL")) == 2
    for invalid in [
        "INSERT INTO client_onboarding_receipts (user_id,request_key,status) VALUES (1,'shared-request-key','cancelled')",
        "UPDATE client_onboarding_receipts SET status='confirmed' WHERE user_id=1",
        "UPDATE client_onboarding_receipts SET result='null'::jsonb WHERE user_id=1",
        "UPDATE client_onboarding_receipts SET status='pending' WHERE user_id=1",
    ]:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(invalid))
    async with engine.connect() as conn:
        await verify(conn)


async def test_journal_deletion_preserves_confirmed_receipt_and_user_deletion_removes_own_barrier(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        journal_id = await conn.scalar(text("""
            INSERT INTO change_logs(user_id,entity_type,action,label,operations,created_at,updated_at)
            VALUES(2,'client','create','Synthetic journal','[]'::jsonb,now(),now()) RETURNING id
        """))
        await conn.execute(text("""
            INSERT INTO client_onboarding_receipts(user_id,request_key,status,request_hash,result,change_log_id)
            VALUES(2,'confirmed-request-key','confirmed',:hash,CAST(:result AS jsonb),:journal)
        """), {"hash": "a" * 64, "journal": journal_id, "result": json.dumps({"client_id": 1, "contact_ids": [], "project_id": None})})
        await conn.execute(text("DELETE FROM change_logs WHERE id=:journal"), {"journal": journal_id})
        row = (await conn.execute(text("SELECT status,result,change_log_id FROM client_onboarding_receipts"))).one()
        assert row == ("confirmed", {"client_id": 1, "contact_ids": [], "project_id": None}, None)
        await conn.execute(text("DELETE FROM users WHERE id=2"))
        assert await conn.scalar(text("SELECT count(*) FROM client_onboarding_receipts")) == 0

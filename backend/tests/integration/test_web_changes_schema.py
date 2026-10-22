"""El paso ``web_changes_v1`` es aditivo, idempotente y su contrato se verifica entero."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.web_changes_schema import MIGRATION, apply, verify

pytestmark = pytest.mark.integration

TABLES = ("web_watches", "web_watch_state", "web_sweep_runs", "web_run_errors", "web_snapshots", "web_changes",
          "web_change_items")


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
            INSERT INTO clients (id,name,contract_type,status,currency,is_internal,is_intermediary_deal,created_at,updated_at)
            VALUES (1,'Fit Generation','monthly','active','EUR',false,false,'2026-01-01','2026-01-02')
        """))
        # Lo que ya hay publicado de fase 1 (webhook cifrado y User-Agent) se conserva.
        await conn.execute(text("""
            INSERT INTO client_web_settings (client_id, slack_webhook_url, slack_enabled, user_agent)
            VALUES (1, 'v1:abc', true, 'Mozilla/5.0 Chrome/126')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


def test_esta_en_el_plan():
    assert MIGRATION in deployment_schema.MIGRATIONS
    assert MIGRATION.version == "20261023_web_changes_v1"


async def test_upgrade_twice_keeps_settings_and_starts_empty(engine):
    async with engine.connect() as conn:
        before = await conn.scalar(text("SELECT to_jsonb(s) FROM client_web_settings s WHERE client_id=1"))
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.connect() as conn:
        after = await conn.scalar(text("SELECT to_jsonb(s) FROM client_web_settings s WHERE client_id=1"))
        # Lo publicado sigue igual; lo nuevo, NULL (= default del código).
        assert {k: after[k] for k in before} == before
        assert after["default_ignore_selectors"] is None and after["sweep_weekdays"] is None
        assert after["max_concurrency"] is None and after["digest_min_severity"] is None
        for table in TABLES:
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


async def test_instalacion_limpia(engine):
    await reset(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)


async def test_apply_es_idempotente(engine):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        await apply(conn)
        await apply(conn)
        await verify(conn)


async def test_el_orm_coincide_con_el_contrato(engine):
    """create_all (tests e init_db) crea lo mismo que la migración: UUID, JSONB, índices parciales, CHECKs."""
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)


async def test_restricciones(engine):
    await deployment_schema.migrate_schema(engine)
    watch, run = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO web_watches (id, client_id, url) VALUES (:id, 1, 'https://fit.es/')"),
                           {"id": watch})
        # Los ids los genera Postgres si no vienen (gen_random_uuid).
        generated = await conn.scalar(text(
            "INSERT INTO web_watches (client_id, url) VALUES (1, 'https://fit.es/b') RETURNING id"))
        assert isinstance(generated, uuid.UUID)
        await conn.execute(text("""INSERT INTO web_sweep_runs (id, client_id, run_date, trigger, started_at)
                                   VALUES (:id, 1, '2026-10-21', 'scheduler', now())"""), {"id": run})
        # Lo manual se repite el mismo día tantas veces como haga falta.
        for _ in range(2):
            await conn.execute(text("""INSERT INTO web_sweep_runs (client_id, run_date, trigger, started_at)
                                       VALUES (1, '2026-10-21', 'manual', now())"""))
        change = await conn.scalar(text("""INSERT INTO web_changes (client_id, watch_id, run_id, max_severity, detected_at)
                                           VALUES (1, :w, :r, 'critical', now()) RETURNING id"""), {"w": watch, "r": run})
        await conn.execute(text("""INSERT INTO web_change_items (change_id, client_id, kind, field, severity, rule_code)
                                   VALUES (:c, 1, 'seo', 'robots', 'critical', 'NOINDEX_ADDED')"""), {"c": change})
    for statement in (
        # Un programado por cliente y día.
        "INSERT INTO web_sweep_runs (client_id, run_date, trigger, started_at) VALUES (1, '2026-10-21', 'scheduler', now())",
        "INSERT INTO web_watches (client_id, url) VALUES (1, 'https://fit.es/')",
        "INSERT INTO web_watches (client_id, url, source) VALUES (1, 'https://fit.es/z', 'robot')",
        "INSERT INTO web_sweep_runs (client_id, run_date, trigger, started_at) VALUES (1, '2026-10-22', 'cron', now())",
        "UPDATE web_changes SET max_severity = 'grave'",
        "UPDATE web_change_items SET kind = 'imagen'",
        "UPDATE client_web_settings SET digest_min_severity = 'todo'",
    ):
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text(statement))
    async with engine.begin() as conn:
        # Purgar barridos NO borra el histórico de cambios (bug real de Vigil, 22-jul-2026).
        await conn.execute(text("DELETE FROM web_sweep_runs"))
        assert await conn.scalar(text("SELECT count(*) FROM web_changes WHERE run_id IS NULL")) == 1
        assert await conn.scalar(text("SELECT count(*) FROM web_change_items")) == 1
        # Borrar el cliente se lo lleva todo.
        await conn.execute(text("DELETE FROM clients WHERE id=1"))
        for table in TABLES:
            assert await conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


@pytest.mark.parametrize("damage", [
    "DROP INDEX uq_web_sweep_runs_scheduler_day",
    "ALTER TABLE web_watches DROP CONSTRAINT uq_web_watches_client_url",
    "ALTER TABLE web_changes DROP CONSTRAINT ck_web_changes_max_severity",
    "ALTER TABLE web_run_errors ALTER COLUMN id TYPE VARCHAR(36)",
    "ALTER TABLE web_changes DROP CONSTRAINT web_changes_run_id_fkey",
    # CASCADE en vez de SET NULL: purgar barridos borraría el histórico.
    "ALTER TABLE web_changes DROP CONSTRAINT web_changes_run_id_fkey; "
    "ALTER TABLE web_changes ADD CONSTRAINT web_changes_run_id_fkey FOREIGN KEY (run_id) "
    "REFERENCES web_sweep_runs(id) ON DELETE CASCADE",
    "ALTER TABLE web_watch_state ALTER COLUMN seo_json TYPE TEXT",
    "ALTER TABLE client_web_settings ALTER COLUMN default_ignore_selectors SET DEFAULT '[\"nav\"]'::jsonb",
    "ALTER TABLE client_web_settings DROP COLUMN sweep_weekdays",
])
async def test_drift_is_rejected(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        for statement in damage.split("; "):
            await conn.execute(text(statement))
        with pytest.raises(RuntimeError):
            await verify(conn)

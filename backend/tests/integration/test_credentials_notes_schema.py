"""Notas de Accesos: la subida cifra las que había en claro y fecha el último cambio de contraseña."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.credentials_notes_schema import MIGRATION
from backend.startup.schema_runner import run_schema_migrations

pytestmark = pytest.mark.integration

ALREADY = encrypt_vault_secret("ya cifrada")


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
            INSERT INTO credentials (id, name, secret_encrypted, notes, created_at) VALUES
              (1, 'WP', 'v1:x', 'PIN 1234', '2026-01-01T00:00:00Z'),
              (2, 'Ads', 'v1:x', '   ', '2026-02-01T00:00:00Z'),
              (3, 'GA', 'v1:x', :already, '2026-03-01T00:00:00Z'),
              (4, 'Sin', 'v1:x', NULL, '2026-04-01T00:00:00Z')
        """), {"already": ALREADY})
        await conn.execute(text("""
            INSERT INTO credential_access_log (credential_id, credential_name, action, detail, at) VALUES
              (1, 'WP', 'update', 'Cambió: usuario, contraseña', '2026-05-01T00:00:00Z'),
              (1, 'WP', 'update', 'Cambió: notas', '2026-06-01T00:00:00Z')
        """))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_la_subida_cifra_las_notas_y_fecha_la_contrasena(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.begin() as conn:
        rows = {row.id: row for row in (await conn.execute(text(
            "SELECT id, notes, secret_changed_at::date AS changed FROM credentials ORDER BY id"))).all()}
        assert decrypt_vault_secret(rows[1].notes) == "PIN 1234"
        assert rows[2].notes is None and rows[4].notes is None
        assert rows[3].notes == ALREADY
        assert [str(rows[i].changed) for i in (1, 2)] == ["2026-05-01", "2026-02-01"]
        with pytest.raises(Exception, match="ck_credentials_notes_encrypted"):
            async with conn.begin_nested():
                await conn.execute(text("UPDATE credentials SET notes='en claro' WHERE id=1"))
        await conn.execute(text("INSERT INTO credential_access_log (credential_id, credential_name, action) VALUES (1, 'WP', 'notes')"))

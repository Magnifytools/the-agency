"""La clave 2FA de Accesos llega con un paso aditivo: los accesos que ya hay no cambian."""
import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.db.models import Base
from backend.startup import deployment_schema, schema_baseline
from backend.startup.credentials_totp_schema import MIGRATION, verify
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
        await conn.execute(text("INSERT INTO credentials (id, name, secret_encrypted) VALUES (1, 'WP', 'v1:x')"))
        await conn.execute(text("INSERT INTO credential_access_log (credential_id, credential_name, action) VALUES (1, 'WP', 'reveal')"))
    yield
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_subida_dos_veces_conserva_lo_guardado_y_admite_totp(engine):
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT name, totp_encrypted FROM credentials"))).one() == ("WP", None)
        await conn.execute(text("INSERT INTO credential_access_log (credential_id, credential_name, action) VALUES (1, 'WP', 'totp')"))
        await conn.execute(text("UPDATE credentials SET totp_encrypted='v1:y' WHERE id=1"))
        with pytest.raises(Exception, match="ck_credentials_totp_encrypted"):
            async with conn.begin_nested():
                await conn.execute(text("UPDATE credentials SET totp_encrypted='JBSWY3DP' WHERE id=1"))
        with pytest.raises(Exception, match="ck_credential_access_log_action"):
            async with conn.begin_nested():
                await conn.execute(text("INSERT INTO credential_access_log (credential_id, credential_name, action) VALUES (1, 'WP', 'otra')"))


@pytest.mark.parametrize("damage", [
    "ALTER TABLE credentials DROP CONSTRAINT ck_credentials_totp_encrypted",
    "ALTER TABLE credential_access_log DROP CONSTRAINT ck_credential_access_log_action; "
    "ALTER TABLE credential_access_log ADD CONSTRAINT ck_credential_access_log_action CHECK (action IN ('reveal'))",
])
async def test_la_deriva_se_rechaza(engine, damage):
    await deployment_schema.migrate_schema(engine)
    async with engine.begin() as conn:
        for statement in damage.split("; "):
            await conn.execute(text(statement))
        with pytest.raises(RuntimeError, match="Unsupported schema"):
            await verify(conn)


async def test_instalacion_limpia_y_orm(engine):
    await reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)

"""Current deployment plan, composed from immutable schema steps."""
from sqlalchemy import text

from backend.startup import schema_baseline
from backend.startup.client_onboarding_schema import (
    MIGRATION as CLIENT_ONBOARDING_MIGRATION,
)
from backend.startup.inbox_recovery_schema_v2 import (
    MIGRATION as INBOX_RECOVERY_MIGRATION,
)
from backend.startup.job_runtime_schema import MIGRATION as JOB_RUNTIME_MIGRATION
from backend.startup.project_review_schema import MIGRATION as PROJECT_REVIEW_MIGRATION
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.task_retirement_schema import (
    MIGRATION as TASK_RETIREMENT_MIGRATION,
)
from backend.startup.usage_origin_schema import MIGRATION as USAGE_ORIGIN_MIGRATION

MIGRATIONS = (
    *schema_baseline.MIGRATIONS, JOB_RUNTIME_MIGRATION, INBOX_RECOVERY_MIGRATION,
    TASK_RETIREMENT_MIGRATION, CLIENT_ONBOARDING_MIGRATION, PROJECT_REVIEW_MIGRATION,
    USAGE_ORIGIN_MIGRATION,
)
EXPECTED_SCHEMA_VERSION = MIGRATIONS[-1].version


async def migrate_schema(engine):
    await run_schema_migrations(engine, MIGRATIONS, schema_baseline.preflight)


async def check_deployment_ready(engine):
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT version,checksum FROM agency_schema_versions ORDER BY version"
        ))).all()
        if list(rows) != sorted((m.version, m.checksum) for m in MIGRATIONS):
            raise RuntimeError("Required schema migration revision is not applied")
        for migration in MIGRATIONS:
            await migration.verify(conn)

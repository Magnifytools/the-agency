"""Current deployment plan, composed from immutable schema steps."""
from sqlalchemy import text

from backend.startup import schema_baseline
from backend.startup.client_onboarding_schema import (
    MIGRATION as CLIENT_ONBOARDING_MIGRATION,
)
from backend.startup.client_share_link_schema import MIGRATION as CLIENT_SHARE_LINK_MIGRATION
from backend.startup.credentials_schema import MIGRATION as CREDENTIALS_MIGRATION
from backend.startup.inbox_recovery_schema_v2 import (
    MIGRATION as INBOX_RECOVERY_MIGRATION,
)
from backend.startup.ga4_schema import MIGRATION as GA4_MIGRATION
from backend.startup.gsc_detail_schema import MIGRATION as GSC_DETAIL_MIGRATION
from backend.startup.gsc_accounts_schema import MIGRATION as GSC_ACCOUNTS_MIGRATION
from backend.startup.gsc_schema import MIGRATION as GSC_MIGRATION
from backend.startup.job_runtime_schema import MIGRATION as JOB_RUNTIME_MIGRATION
from backend.startup.phase0_retirement_schema import MIGRATION as PHASE0_RETIREMENT_MIGRATION
from backend.startup.project_review_schema import MIGRATION as PROJECT_REVIEW_MIGRATION
from backend.startup.report_policy_cadences_schema import (
    MIGRATION as REPORT_POLICY_CADENCES_MIGRATION,
)
from backend.startup.report_policy_legacy_retirement_schema import (
    MIGRATION as REPORT_POLICY_LEGACY_RETIREMENT_MIGRATION,
)
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.task_comment_ai_draft_schema import MIGRATION as TASK_COMMENT_AI_DRAFT_MIGRATION
from backend.startup.task_procedure_schema import MIGRATION as TASK_PROCEDURE_MIGRATION
from backend.startup.task_retirement_schema import (
    MIGRATION as TASK_RETIREMENT_MIGRATION,
)
from backend.startup.usage_origin_schema import MIGRATION as USAGE_ORIGIN_MIGRATION
from backend.startup.vigil_schema import MIGRATION as VIGIL_MIGRATION
from backend.startup.web_changes_schema import MIGRATION as WEB_CHANGES_MIGRATION
from backend.startup.web_uptime_schema import MIGRATION as WEB_UPTIME_MIGRATION

MIGRATIONS = (
    *schema_baseline.MIGRATIONS, JOB_RUNTIME_MIGRATION, INBOX_RECOVERY_MIGRATION,
    TASK_RETIREMENT_MIGRATION, CLIENT_ONBOARDING_MIGRATION, PROJECT_REVIEW_MIGRATION,
    USAGE_ORIGIN_MIGRATION, GSC_MIGRATION, TASK_PROCEDURE_MIGRATION,
    PHASE0_RETIREMENT_MIGRATION, VIGIL_MIGRATION, GSC_ACCOUNTS_MIGRATION, GA4_MIGRATION,
    TASK_COMMENT_AI_DRAFT_MIGRATION, CLIENT_SHARE_LINK_MIGRATION,
    CREDENTIALS_MIGRATION, REPORT_POLICY_CADENCES_MIGRATION,
    REPORT_POLICY_LEGACY_RETIREMENT_MIGRATION, WEB_UPTIME_MIGRATION, GSC_DETAIL_MIGRATION,
    WEB_CHANGES_MIGRATION,
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

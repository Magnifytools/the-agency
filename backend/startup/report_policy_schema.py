"""Additive report-policy schema; no policy seeds or historical backfill."""
from sqlalchemy import text

from backend.db.models import ClientReportPolicy, DigestExternalDeliveryEvent


async def ensure_report_policy_schema(engine):
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(76241312)"))
        await conn.run_sync(lambda sync: ClientReportPolicy.__table__.create(sync, checkfirst=True))
        await conn.run_sync(lambda sync: DigestExternalDeliveryEvent.__table__.create(sync, checkfirst=True))

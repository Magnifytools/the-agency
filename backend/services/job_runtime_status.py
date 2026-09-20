"""Read-only projection of runtime health and non-exclusive delivery heartbeat."""
from datetime import timedelta

from sqlalchemy import select, text

from backend.db.models import JobRuntime
from backend.services.job_catalog import job_definitions
from backend.services.job_runtime import JOB_LOCK_NAMESPACE


ERROR_SUMMARIES = {
    "execution_failed": "No se pudo completar la comprobación. Se volverá a intentar automáticamente.",
    "partial_failure": "Una parte de la comprobación falló. El trabajo confirmado se conserva y se volverá a revisar.",
    "provider_unavailable": "La conexión con el servicio externo falló. Se volverá a intentar automáticamente.",
    "reconnect_required": "Una conexión necesita autorización de nuevo. Revisa la conexión en Ajustes.",
    "timeout": "La comprobación superó su tiempo máximo. Se volverá a intentar automáticamente.",
    "interrupted": "La última comprobación se interrumpió. El proceso la recuperará en su siguiente revisión.",
}


async def list_job_status(db):
    # Use the same DB clock as the scheduler, not the web replica's wall clock.
    now = await db.scalar(text("SELECT clock_timestamp()"))
    rows = {row.key: row for row in (await db.scalars(select(JobRuntime))).all()}
    locks = set((await db.execute(text("""
        SELECT objid::bigint FROM pg_locks
        WHERE locktype='advisory' AND classid=:namespace AND objsubid=2
          AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
    """), {"namespace": JOB_LOCK_NAMESPACE})).scalars())
    jobs = []
    for definition in job_definitions():
        spec = definition.spec
        row = rows.get(spec.key)
        summary = None
        unfinished = bool(row and row.started_at and (not row.finished_at or row.started_at > row.finished_at))
        if unfinished and spec.key != "deliveries" and spec.lock_id in locks:
            state = "running"
        elif not definition.enabled:
            state = "paused"
        elif row is None:
            state = "never"
        elif unfinished:
            state = "stale"
            summary = ERROR_SUMMARIES["interrupted"]
        elif row.error_code:
            state = "failed"
            summary = ERROR_SUMMARIES.get(row.error_code, ERROR_SUMMARIES["execution_failed"])
        elif not row.finished_at:
            state = "never"
        elif not row.next_run_at or row.next_run_at + timedelta(seconds=90) < now:
            state = "stale"
            summary = "No hay una comprobación reciente. El proceso necesita revisión."
        else:
            state = "success"
        jobs.append({
            "key": spec.key, "label": definition.label, "description": definition.description,
            "state": state, "last_success_at": row.success_at if row else None,
            "started_at": row.started_at if row and state == "running" else None,
            "last_failure_at": row.finished_at if row and row.error_code else None,
            "failure_summary": summary, "paused_reason": definition.paused_reason if state == "paused" else None,
        })
    return {"jobs": jobs}


async def record_delivery_cycle(engine, *, failed: bool):
    """A completed queue pass, NOT confirmation that a provider accepted a send.

    Workers keep independent delivery leases; this short upsert is only a health
    observation. The latest completed observation wins, using the DB clock after
    any concurrent row-lock wait. Provider results remain in DeliveryAttempt.
    """
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL lock_timeout = '2s'"))
        await conn.execute(text("SET LOCAL statement_timeout = '3s'"))
        await conn.execute(text("""
            INSERT INTO job_runtime (key) VALUES ('deliveries') ON CONFLICT (key) DO NOTHING
        """))
        await conn.execute(text("SELECT key FROM job_runtime WHERE key='deliveries' FOR UPDATE"))
        await conn.execute(text("""
            UPDATE job_runtime SET finished_at=clock_timestamp(),
              success_at=CASE WHEN :failed THEN success_at ELSE clock_timestamp() END,
              error_code=CASE WHEN :failed THEN 'execution_failed' ELSE NULL END,
              next_run_at=clock_timestamp() + interval '45 seconds'
            WHERE key='deliveries'
        """), {"failed": failed})

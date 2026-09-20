"""Real runtime state, advisory ownership, admin ACL and provider-safe output."""
import asyncio
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import text

from backend.db.models import JobRuntime
from backend.services.job_catalog import JobDefinition
from backend.services.job_runtime import JOB_LOCK_NAMESPACE, JobSpec
from backend.services.job_runtime_status import record_delivery_cycle


async def test_member_cannot_read_global_runtime(member_client):
    response = await member_client.get("/api/admin/job-runtime")
    assert response.status_code == 403


async def test_admin_projection_covers_states_and_never_echoes_raw_error(admin_client, db_session, engine):
    now = await db_session.scalar(text("SELECT clock_timestamp()"))
    # A running old replica remains visible during a rollout with a new gate off.
    definitions = [JobDefinition(JobSpec(key, 12000 + i, 60), key, "scope", "Paused by configuration" if key in {"paused", "running"} else None)
                   for i, key in enumerate(["running", "stale", "failed", "paused", "never", "success", "interrupted"])]
    for key in ("running", "stale", "failed", "paused", "success", "interrupted"):
        db_session.add(JobRuntime(key=key, started_at=now - timedelta(minutes=10),
            finished_at=None if key in {"running", "interrupted"} else now - timedelta(minutes=9),
            success_at=now - timedelta(minutes=9),
            error_code="secret-token https://provider.example/private" if key == "failed" else None,
            next_run_at=now - timedelta(minutes=3) if key == "stale" else now + timedelta(minutes=1)))
    await db_session.flush()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:namespace,12000)"), {"namespace": JOB_LOCK_NAMESPACE})
        try:
            with patch("backend.services.job_runtime_status.job_definitions", return_value=definitions):
                response = await admin_client.get("/api/admin/job-runtime")
            assert response.status_code == 200
            states = {r["key"]: r["state"] for r in response.json()["jobs"]}
            assert states == {"running": "running", "stale": "stale", "failed": "failed", "paused": "paused",
                              "never": "never", "success": "success", "interrupted": "stale"}
            assert "secret-token" not in response.text and "provider.example" not in response.text
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:namespace,12000)"), {"namespace": JOB_LOCK_NAMESPACE})


async def test_delivery_observation_does_not_take_global_job_lock(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM job_runtime WHERE key='deliveries'"))
    try:
        async with engine.connect() as locked:
            await locked.execute(text("SELECT pg_advisory_lock(:namespace,2)"), {"namespace": JOB_LOCK_NAMESPACE})
            try:
                await asyncio.wait_for(record_delivery_cycle(engine, failed=False), timeout=2)
            finally:
                await locked.execute(text("SELECT pg_advisory_unlock(:namespace,2)"), {"namespace": JOB_LOCK_NAMESPACE})
        async with engine.connect() as conn:
            first = (await conn.execute(text("SELECT * FROM job_runtime WHERE key='deliveries'"))).mappings().one()
        await record_delivery_cycle(engine, failed=True)
        async with engine.connect() as conn:
            second = (await conn.execute(text("SELECT * FROM job_runtime WHERE key='deliveries'"))).mappings().one()
        assert first["success_at"] == second["success_at"]
        assert second["error_code"] == "execution_failed"
        assert second["finished_at"] > first["finished_at"]
        assert second["started_at"] is None
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM job_runtime WHERE key='deliveries'"))

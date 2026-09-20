import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text

from backend.services import job_runtime
from backend.services.job_runtime import JobFailure, JobSpec, run_job

pytestmark = pytest.mark.asyncio


async def _reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM job_runtime"))


async def _row(engine, key="test-job"):
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT * FROM job_runtime WHERE key=:key"
        ), {"key": key})).mappings().one()


@pytest.fixture(autouse=True)
async def clean_runtime(engine):
    await _reset(engine)
    yield
    await _reset(engine)


async def test_concurrent_workers_execute_due_cycle_once(engine):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    spec = JobSpec("test-job", 11001, 300)

    async def work():
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()

    first = asyncio.create_task(run_job(engine, spec, work))
    await entered.wait()
    assert await run_job(engine, spec, work) is False
    release.set()
    assert await first is True
    assert calls == 1


async def test_completed_cycle_is_not_due_again(engine):
    calls = 0
    spec = JobSpec("test-job", 11002, 300)

    async def work():
        nonlocal calls
        calls += 1

    assert await run_job(engine, spec, work) is True
    assert await run_job(engine, spec, work) is False
    row = await _row(engine)
    assert row["success_at"] == row["finished_at"]
    assert row["next_run_at"] > row["finished_at"]
    assert calls == 1


async def test_new_job_can_wait_for_first_scheduled_run(engine):
    called = False
    spec = JobSpec("test-job", 11012, 300, run_on_startup=False)

    async def work():
        nonlocal called
        called = True

    assert await run_job(engine, spec, work) is False
    row = await _row(engine)
    assert called is False
    assert row["started_at"] is None
    assert row["finished_at"] is None
    assert row["next_run_at"] is not None
    async with engine.connect() as conn:
        assert row["next_run_at"] > await conn.scalar(text("SELECT clock_timestamp()"))


async def test_existing_interrupted_due_job_recovers_despite_startup_delay(engine):
    spec = JobSpec("test-job", 11013, 300, run_on_startup=False)
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO job_runtime (key, started_at, next_run_at)
            VALUES (:key, clock_timestamp() - interval '1 minute',
                    clock_timestamp() - interval '1 minute')
        """), {"key": spec.key})

    assert await run_job(engine, spec, lambda: asyncio.sleep(0)) is True
    row = await _row(engine)
    assert row["success_at"] == row["finished_at"]
    assert row["next_run_at"] > row["finished_at"]


async def test_work_spanning_multiple_heartbeats_finishes_cleanly(engine, monkeypatch):
    spec = JobSpec("test-job", 11010, 300)
    monkeypatch.setattr(job_runtime, "HEARTBEAT_SECONDS", 0.01)

    await run_job(engine, spec, lambda: asyncio.sleep(0.06))

    row = await _row(engine)
    assert row["success_at"] == row["finished_at"]
    assert row["error_code"] is None


async def test_finish_waits_for_inflight_heartbeat_transaction(engine, monkeypatch):
    spec = JobSpec("test-job", 11011, 300)
    check_entered, release_check = asyncio.Event(), asyncio.Event()
    real_owns = job_runtime._owns_lock
    checks = 0

    async def gated_owns(connection, lock_id):
        nonlocal checks
        checks += 1
        if checks == 1:
            check_entered.set()
            await release_check.wait()
        return await real_owns(connection, lock_id)

    async def work():
        await check_entered.wait()

    monkeypatch.setattr(job_runtime, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(job_runtime, "_owns_lock", gated_owns)
    running = asyncio.create_task(run_job(engine, spec, work))
    await check_entered.wait()
    await asyncio.sleep(0)
    assert not running.done()
    release_check.set()
    assert await running is True
    assert (await _row(engine))["success_at"] is not None


async def test_lock_id_matches_pg_locks_unsigned_representation():
    with pytest.raises(ValueError, match="non-negative"):
        JobSpec("invalid", -1, 300)


async def test_failure_is_sanitized_scheduled_for_retry_and_propagated(engine):
    spec = JobSpec("test-job", 11003, 300)

    async def work():
        raise ValueError("secret provider response")

    with pytest.raises(ValueError, match="secret provider response"):
        await run_job(engine, spec, work)
    row = await _row(engine)
    assert row["error_code"] == "execution_failed"
    assert row["success_at"] is None
    assert timedelta(seconds=0) < row["next_run_at"] - row["finished_at"] <= timedelta(seconds=60)


async def test_job_failure_uses_only_whitelisted_code(engine):
    spec = JobSpec("test-job", 11004, 300)

    async def work():
        raise JobFailure("raw-secret-code")

    with pytest.raises(JobFailure) as error:
        await run_job(engine, spec, work)
    assert error.value.code == "execution_failed"
    assert (await _row(engine))["error_code"] == "execution_failed"


async def test_expected_partial_failure_is_persisted_without_message(engine):
    spec = JobSpec("test-job", 11009, 300)

    async def work():
        raise JobFailure("partial_failure")

    with pytest.raises(JobFailure) as error:
        await run_job(engine, spec, work)
    assert error.value.code == "partial_failure"
    row = await _row(engine)
    assert row["error_code"] == "partial_failure"
    assert set(row) == {
        "key", "started_at", "finished_at", "success_at", "error_code", "next_run_at",
    }


async def test_cancel_leaves_interrupted_state_due_for_restart(engine):
    entered, never = asyncio.Event(), asyncio.Event()
    spec = JobSpec("test-job", 11005, 300)

    async def blocked():
        entered.set()
        await never.wait()

    task = asyncio.create_task(run_job(engine, spec, blocked))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    interrupted = await _row(engine)
    assert interrupted["started_at"] is not None
    assert interrupted["finished_at"] is None
    assert interrupted["next_run_at"] is None

    assert await run_job(engine, spec, lambda: asyncio.sleep(0)) is True
    assert (await _row(engine))["success_at"] is not None


async def test_timeout_cancels_work_and_records_failure(engine):
    cancelled = asyncio.Event()
    spec = JobSpec("test-job", 11006, 300, timeout_seconds=0.05)

    async def work():
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    with pytest.raises(JobFailure) as error:
        await run_job(engine, spec, work)
    assert error.value.code == "timeout"
    assert cancelled.is_set()
    assert (await _row(engine))["error_code"] == "timeout"


async def test_lost_lock_cancels_work_without_writing_finish(engine, monkeypatch):
    entered, cancelled = asyncio.Event(), asyncio.Event()
    spec = JobSpec("test-job", 11007, 300)
    real_owns = job_runtime._owns_lock
    checks = 0

    async def lose_after_start(connection, lock_id):
        nonlocal checks
        checks += 1
        if checks == 1:
            assert await connection.scalar(text(
                "SELECT pg_advisory_unlock(:namespace, :lock_id)"
            ), {"namespace": job_runtime.JOB_LOCK_NAMESPACE, "lock_id": lock_id}) is True
            return False
        return await real_owns(connection, lock_id)

    async def work():
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setattr(job_runtime, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(job_runtime, "_owns_lock", lose_after_start)
    with pytest.raises(JobFailure) as error:
        await run_job(engine, spec, work)
    assert error.value.code == "lock_lost"
    assert entered.is_set() and cancelled.is_set()
    row = await _row(engine)
    assert row["finished_at"] is None and row["success_at"] is None


async def test_daily_next_run_uses_business_midnight_across_dst():
    spec = JobSpec("daily", 11008, 86400, daily=True)
    before = job_runtime.datetime(2026, 3, 29, 21, 0, tzinfo=job_runtime.timezone.utc)
    due = spec.next_run(before, failed=False)
    assert due.isoformat() == "2026-03-29T22:01:00+00:00"
    assert spec.next_run(before, failed=True) == before + timedelta(seconds=60)

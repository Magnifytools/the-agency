"""Coordination and durable health state for singleton background jobs."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from backend.services.temporal import business_zone


JOB_LOCK_NAMESPACE = 76241319
HEARTBEAT_SECONDS = 1.0
CONTROL_STATEMENT_TIMEOUT = "5s"
CONTROL_CLEANUP_TIMEOUT_SECONDS = 6.0
ALLOWED_ERROR_CODES = frozenset({
    "execution_failed", "interrupted", "lock_lost", "partial_failure",
    "provider_unavailable", "reconnect_required", "timeout",
})


class JobFailure(RuntimeError):
    """Expected, sanitized failure suitable for persisted operational state."""

    def __init__(self, code: str):
        self.code = code if code in ALLOWED_ERROR_CODES else "execution_failed"
        super().__init__(self.code)


@dataclass(frozen=True)
class JobSpec:
    key: str
    lock_id: int
    interval_seconds: int
    timeout_seconds: int = 300
    daily: bool = False
    run_on_startup: bool = True

    def __post_init__(self) -> None:
        if not self.key or len(self.key) > 64:
            raise ValueError("Job key must contain 1 to 64 characters")
        if not 0 <= self.lock_id < 2**31:
            raise ValueError("Job lock_id must be a non-negative PostgreSQL int4")
        if self.interval_seconds <= 0 or self.timeout_seconds <= 0:
            raise ValueError("Job intervals and timeouts must be positive")

    def next_run(self, now: datetime, failed: bool) -> datetime:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if failed:
            return now + timedelta(seconds=min(60, self.interval_seconds))
        if not self.daily:
            return now + timedelta(seconds=self.interval_seconds)
        local = now.astimezone(business_zone())
        candidate = datetime.combine(local.date(), time(0, 1), business_zone())
        if local >= candidate:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)


async def _owns_lock(connection: AsyncConnection, lock_id: int) -> bool:
    """Verify this exact backend still owns the two-int advisory session lock."""
    return bool(await connection.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_locks
            WHERE locktype='advisory' AND granted
              AND pid=pg_backend_pid() AND objsubid=2
              AND classid::bigint=:namespace AND objid::bigint=:lock_id
        )
    """), {"namespace": JOB_LOCK_NAMESPACE, "lock_id": lock_id}))


async def _set_control_timeouts(connection: AsyncConnection) -> None:
    await connection.execute(text(
        f"SET LOCAL lock_timeout='{CONTROL_STATEMENT_TIMEOUT}'"
    ))
    await connection.execute(text(
        f"SET LOCAL statement_timeout='{CONTROL_STATEMENT_TIMEOUT}'"
    ))


async def _heartbeat(
    connection: AsyncConnection, lock_id: int, stop: asyncio.Event,
) -> None:
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        try:
            async with connection.begin():
                await _set_control_timeouts(connection)
                owned = await _owns_lock(connection, lock_id)
            if not owned:
                raise JobFailure("lock_lost")
        except asyncio.CancelledError:
            raise
        except JobFailure:
            raise
        except Exception as exc:
            raise JobFailure("lock_lost") from exc


async def _db_now(connection: AsyncConnection) -> datetime:
    return await connection.scalar(text("SELECT clock_timestamp()"))


async def _start_if_due(connection: AsyncConnection, spec: JobSpec) -> bool:
    async with connection.begin():
        await _set_control_timeouts(connection)
        initial_now = await _db_now(connection)
        await connection.execute(text("""
            INSERT INTO job_runtime (key, next_run_at) VALUES (:key, :initial_next_run)
            ON CONFLICT (key) DO NOTHING
        """), {
            "key": spec.key,
            "initial_next_run": None if spec.run_on_startup else spec.next_run(initial_now, False),
        })
        row = (await connection.execute(text("""
            SELECT next_run_at FROM job_runtime WHERE key=:key FOR UPDATE
        """), {"key": spec.key})).one()
        now = await _db_now(connection)
        if row.next_run_at is not None and row.next_run_at > now:
            return False
        await connection.execute(text("""
            UPDATE job_runtime
            SET started_at=:now, error_code=NULL
            WHERE key=:key
        """), {"key": spec.key, "now": now})
        return True


async def _finish(
    connection: AsyncConnection, spec: JobSpec, *, failed: bool, error_code: str | None,
) -> None:
    async with connection.begin():
        await _set_control_timeouts(connection)
        if not await _owns_lock(connection, spec.lock_id):
            raise JobFailure("lock_lost")
        now = await _db_now(connection)
        await connection.execute(text("""
            UPDATE job_runtime SET
                finished_at=:now,
                success_at=CASE WHEN :failed THEN success_at ELSE :now END,
                error_code=:error_code,
                next_run_at=:next_run
            WHERE key=:key
        """), {
            "key": spec.key, "now": now, "failed": failed,
            "error_code": error_code,
            "next_run": spec.next_run(now, failed),
        })


async def _release_lock(connection: AsyncConnection, lock_id: int) -> None:
    if connection.in_transaction():
        await connection.rollback()
    async with connection.begin():
        await _set_control_timeouts(connection)
        released = await connection.scalar(
            text("SELECT pg_advisory_unlock(:namespace, :lock_id)"),
            {"namespace": JOB_LOCK_NAMESPACE, "lock_id": lock_id},
        )
    if released is not True:
        raise RuntimeError("Job advisory lock release was uncertain")


async def _cleanup_connection(
    connection: AsyncConnection, lock_id: int, *, lock_possible: bool,
) -> None:
    try:
        if lock_possible:
            await _release_lock(connection, lock_id)
    except BaseException:
        try:
            await connection.invalidate()
        finally:
            await connection.close()
        raise
    finally:
        if not connection.closed:
            await connection.close()


async def _run_with_heartbeat(
    lock_connection: AsyncConnection,
    spec: JobSpec,
    operation: Callable[[], Awaitable[None]],
) -> None:
    stop = asyncio.Event()
    work = asyncio.create_task(operation(), name=f"job-work:{spec.key}")
    heartbeat = asyncio.create_task(
        _heartbeat(lock_connection, spec.lock_id, stop), name=f"job-heartbeat:{spec.key}",
    )
    try:
        done, _ = await asyncio.wait(
            {work, heartbeat}, timeout=spec.timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            stop.set()
            await heartbeat
            raise JobFailure("timeout")
        if heartbeat in done:
            error = heartbeat.exception()
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            raise error or JobFailure("lock_lost")
        stop.set()
        # A heartbeat query may already be in flight. Let its bounded control
        # transaction finish before the final state transaction starts.
        await heartbeat
        await work
    finally:
        stop.set()
        if not heartbeat.done():
            heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        if not work.done():
            work.cancel()
        # Consume the result even when work completed concurrently with a
        # failing heartbeat, avoiding an unobserved task exception.
        await asyncio.gather(work, return_exceptions=True)


async def run_job(
    engine: AsyncEngine,
    spec: JobSpec,
    operation: Callable[[], Awaitable[None]],
) -> bool:
    """Run one due singleton cycle; return False when another worker owns it or it is not due."""
    lock_connection = await engine.connect()
    lock_possible = False
    original_error: BaseException | None = None
    try:
        # Once the non-blocking acquisition is sent, cancellation may arrive
        # after PostgreSQL granted it. Cleanup must then unlock or invalidate.
        lock_possible = True
        async with lock_connection.begin():
            await _set_control_timeouts(lock_connection)
            acquired = bool(await lock_connection.scalar(text(
                "SELECT pg_try_advisory_lock(:namespace, :lock_id)"
            ), {"namespace": JOB_LOCK_NAMESPACE, "lock_id": spec.lock_id}))
        if not acquired:
            lock_possible = False
            return False
        if not await _start_if_due(lock_connection, spec):
            return False

        try:
            await _run_with_heartbeat(lock_connection, spec, operation)
        except asyncio.CancelledError:
            raise  # started_at remains newer than finished_at; due stays unchanged.
        except Exception as exc:
            code = exc.code if isinstance(exc, JobFailure) else "execution_failed"
            try:
                await _finish(lock_connection, spec, failed=True, error_code=code)
            except JobFailure as lock_error:
                if lock_error.code == "lock_lost":
                    raise lock_error from exc
                raise
            raise
        await _finish(lock_connection, spec, failed=False, error_code=None)
        return True
    except BaseException as exc:
        original_error = exc
        raise
    finally:
        cleanup = asyncio.create_task(asyncio.wait_for(
            _cleanup_connection(
                lock_connection, spec.lock_id, lock_possible=lock_possible,
            ),
            timeout=CONTROL_CLEANUP_TIMEOUT_SECONDS,
        ))
        try:
            await asyncio.shield(cleanup)
        except BaseException:
            try:
                await cleanup
            except BaseException:
                if original_error is None:
                    raise
            if original_error is None:
                raise

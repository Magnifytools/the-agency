import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from backend.startup.schema_runner import Migration, run_schema_migrations
from backend.startup import schema_runner

pytestmark = pytest.mark.asyncio


async def _isolated_engine(engine):
    schema = "schema_runner_" + uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_async_engine(
        engine.url, connect_args={"server_settings": {"search_path": schema}},
    )
    return schema, isolated


async def _drop_isolated(engine, schema, isolated):
    await isolated.dispose()
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


async def _preflight(conn: AsyncConnection):
    await conn.execute(text("SELECT 1"))


async def _noop(_conn):
    return None


def _create_marker(version="001", checksum="marker-v1", *, entered=None, release=None):
    async def apply(conn):
        if entered is not None:
            entered.set()
        if release is not None:
            await release.wait()
        await conn.execute(text("CREATE TABLE marker (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO marker VALUES (1)"))

    async def verify(conn):
        assert await conn.scalar(text("SELECT count(*) FROM marker")) == 1

    return Migration(version, checksum, apply, verify)


async def test_concurrent_runners_apply_once_and_release_lock(engine):
    schema, isolated = await _isolated_engine(engine)
    entered, release = asyncio.Event(), asyncio.Event()
    migration = _create_marker(entered=entered, release=release)
    try:
        first = asyncio.create_task(run_schema_migrations(isolated, [migration], _preflight))
        await entered.wait()
        second = asyncio.create_task(run_schema_migrations(isolated, [migration], _preflight))
        await asyncio.sleep(0.1)
        assert not second.done()
        release.set()
        await asyncio.gather(first, second)
        async with isolated.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM marker")) == 1
            assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions")) == 1
        # A third connection can acquire the same session lock after both runs.
        await asyncio.wait_for(run_schema_migrations(isolated, [migration], _preflight), 2)
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_failed_step_rolls_back_ddl_and_ledger_then_reruns(engine):
    schema, isolated = await _isolated_engine(engine)
    attempts = 0

    async def apply(conn):
        nonlocal attempts
        attempts += 1
        await conn.execute(text("CREATE TABLE retry_marker (id INTEGER PRIMARY KEY)"))

    async def fail_verify(conn):
        raise RuntimeError("contract missing")

    async def pass_verify(conn):
        await conn.execute(text("SELECT id FROM retry_marker LIMIT 0"))

    try:
        with pytest.raises(RuntimeError, match="contract missing"):
            await run_schema_migrations(
                isolated, [Migration("001", "retry-v1", apply, fail_verify)], _preflight,
            )
        async with isolated.connect() as conn:
            assert await conn.scalar(text("SELECT to_regclass('retry_marker')")) is None
            assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions")) == 0
        await run_schema_migrations(
            isolated, [Migration("001", "retry-v1", apply, pass_verify)], _preflight,
        )
        await run_schema_migrations(
            isolated, [Migration("001", "retry-v1", apply, pass_verify)], _preflight,
        )
        assert attempts == 2
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_checksum_drift_is_rejected_without_reapplying(engine):
    schema, isolated = await _isolated_engine(engine)
    try:
        await run_schema_migrations(isolated, [_create_marker()], _preflight)
        with pytest.raises(RuntimeError, match="checksum drift: 001"):
            await run_schema_migrations(
                isolated, [_create_marker(checksum="changed")], _preflight,
            )
    finally:
        await _drop_isolated(engine, schema, isolated)


@pytest.mark.parametrize("history", [
    [("unknown", "x")],
    [("002", "two")],
])
async def test_unknown_or_gapped_history_is_rejected(engine, history):
    schema, isolated = await _isolated_engine(engine)

    plan = [Migration("001", "one", _noop, _noop), Migration("002", "two", _noop, _noop)]
    try:
        async with isolated.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE agency_schema_versions (
                    version VARCHAR(100) PRIMARY KEY, checksum VARCHAR(128) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            for version, checksum in history:
                await conn.execute(text(
                    "INSERT INTO agency_schema_versions(version, checksum) VALUES (:v, :c)"
                ), {"v": version, "c": checksum})
        expected = "Unknown" if history[0][0] == "unknown" else "gaps"
        with pytest.raises(RuntimeError, match=expected):
            await run_schema_migrations(isolated, plan, _preflight)
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_preflight_failure_does_not_create_ledger(engine):
    schema, isolated = await _isolated_engine(engine)

    async def reject(_conn):
        raise RuntimeError("unsupported database shape")

    try:
        with pytest.raises(RuntimeError, match="unsupported database shape"):
            await run_schema_migrations(
                isolated, [Migration("001", "noop", _noop, _noop)], reject,
            )
        async with isolated.connect() as conn:
            assert await conn.scalar(text("SELECT to_regclass('agency_schema_versions')")) is None
        # The failed run released the session lock and did not poison the pool.
        await asyncio.wait_for(run_schema_migrations(
            isolated, [Migration("001", "noop", _noop, _noop)], _preflight,
        ), 2)
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_cancellation_rolls_back_step_and_releases_session_lock(engine):
    schema, isolated = await _isolated_engine(engine)
    entered, never = asyncio.Event(), asyncio.Event()

    async def blocked_apply(conn):
        await conn.execute(text("CREATE TABLE cancelled_marker (id INTEGER PRIMARY KEY)"))
        entered.set()
        await never.wait()

    async def verify(conn):
        await conn.execute(text("SELECT id FROM cancelled_marker LIMIT 0"))

    interrupted = Migration("001", "cancel-v1", blocked_apply, verify)
    try:
        task = asyncio.create_task(run_schema_migrations(isolated, [interrupted], _preflight))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with isolated.connect() as conn:
            assert await conn.scalar(text("SELECT to_regclass('cancelled_marker')")) is None
            assert await conn.scalar(text("SELECT count(*) FROM agency_schema_versions")) == 0

        async def apply(conn):
            await conn.execute(text("CREATE TABLE cancelled_marker (id INTEGER PRIMARY KEY)"))

        await asyncio.wait_for(run_schema_migrations(
            isolated, [Migration("001", "cancel-v1", apply, verify)], _preflight,
        ), 2)
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_empty_plan_is_rejected_before_connecting(engine):
    with pytest.raises(ValueError, match="must not be empty"):
        await run_schema_migrations(engine, [], _preflight)


async def test_failed_unlock_invalidates_session_and_does_not_retain_lock(engine, monkeypatch):
    schema, isolated = await _isolated_engine(engine)
    real_release = schema_runner._release_session_lock
    release_calls = 0

    async def fail_first_release(connection):
        nonlocal release_calls
        release_calls += 1
        if release_calls == 1:
            raise RuntimeError("simulated unlock failure")
        await real_release(connection)

    monkeypatch.setattr(schema_runner, "_release_session_lock", fail_first_release)
    migration = Migration("001", "noop-v1", _noop, _noop)
    try:
        with pytest.raises(RuntimeError, match="simulated unlock failure"):
            await run_schema_migrations(isolated, [migration], _preflight)
        # The ledger transaction committed, but invalidating the physical
        # session released its advisory lock. A new session must not time out.
        await asyncio.wait_for(
            run_schema_migrations(isolated, [migration], _preflight), timeout=2,
        )
        assert release_calls == 2
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_cleanup_failure_does_not_replace_step_error(engine, monkeypatch):
    schema, isolated = await _isolated_engine(engine)

    async def fail_apply(_conn):
        raise RuntimeError("original apply failure")

    async def fail_release(_connection):
        raise RuntimeError("secondary cleanup failure")

    monkeypatch.setattr(schema_runner, "_release_session_lock", fail_release)
    try:
        with pytest.raises(RuntimeError, match="original apply failure"):
            await run_schema_migrations(
                isolated, [Migration("001", "fail-v1", fail_apply, _noop)], _preflight,
            )
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_cancellation_while_waiting_for_lock_does_not_leak_connection(engine):
    schema, isolated = await _isolated_engine(engine)
    migration = Migration("001", "noop-v1", _noop, _noop)
    holder = await isolated.connect()
    try:
        async with holder.begin():
            await holder.execute(text("SELECT pg_advisory_lock(:key)"), {
                "key": schema_runner.SCHEMA_MIGRATION_LOCK,
            })
        waiting = asyncio.create_task(run_schema_migrations(isolated, [migration], _preflight))
        await asyncio.sleep(0.1)
        assert not waiting.done()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        async with holder.begin():
            assert await holder.scalar(text("SELECT pg_advisory_unlock(:key)"), {
                "key": schema_runner.SCHEMA_MIGRATION_LOCK,
            }) is True
        await asyncio.wait_for(
            run_schema_migrations(isolated, [migration], _preflight), timeout=2,
        )
    finally:
        await holder.close()
        await _drop_isolated(engine, schema, isolated)


async def test_step_timeouts_are_local_to_transactions(engine):
    schema, isolated = await _isolated_engine(engine)
    observed = []

    async def observe(conn):
        observed.append((
            await conn.scalar(text("SELECT current_setting('lock_timeout')")),
            await conn.scalar(text("SELECT current_setting('statement_timeout')")),
        ))

    try:
        async with isolated.connect() as conn:
            defaults = (
                await conn.scalar(text("SELECT current_setting('lock_timeout')")),
                await conn.scalar(text("SELECT current_setting('statement_timeout')")),
            )
        await run_schema_migrations(
            isolated, [Migration("001", "timeouts-v1", observe, observe)], _preflight,
        )
        assert observed == [("5s", "1min")] * 3
        async with isolated.connect() as conn:
            restored = (
                await conn.scalar(text("SELECT current_setting('lock_timeout')")),
                await conn.scalar(text("SELECT current_setting('statement_timeout')")),
            )
        assert restored == defaults
    finally:
        await _drop_isolated(engine, schema, isolated)


async def test_duplicate_ledger_versions_are_rejected(engine):
    schema, isolated = await _isolated_engine(engine)
    migration = Migration("001", "one", _noop, _noop)
    try:
        async with isolated.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE agency_schema_versions (
                    version VARCHAR(100) NOT NULL, checksum VARCHAR(128) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            await conn.execute(text("""
                INSERT INTO agency_schema_versions(version,checksum)
                VALUES ('001','one'),('001','one')
            """))
        with pytest.raises(RuntimeError, match="duplicate versions"):
            await run_schema_migrations(isolated, [migration], _preflight)
    finally:
        await _drop_isolated(engine, schema, isolated)

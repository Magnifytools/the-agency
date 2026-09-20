"""Versioned, schema-only migration runner.

The caller supplies the supported schema shapes in ``preflight`` and the
ordered migration plan.  This module never stamps Alembic, seeds business
data, or interprets existing rows.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Awaitable, Callable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


MigrationCallback = Callable[[AsyncConnection], Awaitable[None]]


@dataclass(frozen=True)
class Migration:
    version: str
    checksum: str
    apply: MigrationCallback
    verify: MigrationCallback


SCHEMA_MIGRATION_LOCK = 76241318
SCHEMA_LOCK_TIMEOUT = "5s"
SCHEMA_STATEMENT_TIMEOUT = "60s"


async def _set_local_step_timeouts(connection: AsyncConnection) -> None:
    await connection.execute(text(f"SET LOCAL lock_timeout = '{SCHEMA_LOCK_TIMEOUT}'"))
    await connection.execute(text(f"SET LOCAL statement_timeout = '{SCHEMA_STATEMENT_TIMEOUT}'"))


def _validate_plan(migrations: Sequence[Migration]) -> None:
    if not migrations:
        raise ValueError("Schema migration plan must not be empty")
    versions: set[str] = set()
    for migration in migrations:
        if not migration.version or not migration.checksum:
            raise ValueError("Schema migration version and checksum must be non-empty")
        if migration.version in versions:
            raise ValueError(f"Duplicate schema migration version: {migration.version}")
        versions.add(migration.version)


async def _release_session_lock(connection: AsyncConnection) -> None:
    """Release the session lock before the connection can return to its pool."""
    if connection.in_transaction():
        await connection.rollback()
    async with connection.begin():
        released = await connection.scalar(
            text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEMA_MIGRATION_LOCK},
        )
        if released is not True:
            raise RuntimeError("Schema migration advisory lock was not held")


async def _close_runner_connection(
    connection: AsyncConnection, *, lock_acquired: bool,
) -> None:
    try:
        if lock_acquired:
            await _release_session_lock(connection)
    except BaseException:
        # close() normally returns a physical connection to the pool. If the
        # unlock path is uncertain, invalidate it so PostgreSQL ends the
        # session and necessarily releases every session advisory lock.
        try:
            await connection.invalidate()
        finally:
            await connection.close()
        raise
    finally:
        if not connection.closed:
            await connection.close()


async def run_schema_migrations(
    engine: AsyncEngine,
    migrations: Sequence[Migration],
    preflight: MigrationCallback,
) -> None:
    """Apply an ordered migration prefix exactly once.

    ``preflight`` runs before the ledger is created. Each pending step owns one
    transaction containing apply, verify and ledger insert. All step contracts
    are verified again at the end, including contracts for previously applied
    versions.
    """
    plan = tuple(migrations)
    _validate_plan(plan)
    connection = await engine.connect()
    lock_cleanup_required = False
    try:
        # SET LOCAL cannot escape into the pool. The advisory lock is session
        # scoped, so it remains held after this acquisition transaction commits.
        async with connection.begin():
            await connection.execute(text(f"SET LOCAL lock_timeout = '{SCHEMA_LOCK_TIMEOUT}'"))
            # Cancellation can arrive after PostgreSQL grants the lock but
            # before execute() returns. From this point onward cleanup must
            # either unlock successfully or invalidate the physical session.
            lock_cleanup_required = True
            await connection.execute(
                text("SELECT pg_advisory_lock(:key)"), {"key": SCHEMA_MIGRATION_LOCK},
            )

        # A rejected database shape must remain wholly untouched, including no
        # migration ledger created merely by probing it.
        async with connection.begin():
            await preflight(connection)

        async with connection.begin():
            await _set_local_step_timeouts(connection)
            await connection.execute(text("""
                CREATE TABLE IF NOT EXISTS agency_schema_versions (
                    version VARCHAR(100) PRIMARY KEY,
                    checksum VARCHAR(128) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))

        async with connection.begin():
            rows = (await connection.execute(text(
                "SELECT version, checksum FROM agency_schema_versions"
            ))).all()

        recorded = {row.version: row.checksum for row in rows}
        if len(rows) != len(recorded):
            raise RuntimeError("Schema migration history contains duplicate versions")
        known = {migration.version for migration in plan}
        unknown = sorted(set(recorded) - known)
        if unknown:
            raise RuntimeError(f"Unknown schema migration versions: {', '.join(unknown)}")

        applied_count = len(recorded)
        expected_prefix = {migration.version for migration in plan[:applied_count]}
        if set(recorded) != expected_prefix:
            missing = [m.version for m in plan[:applied_count] if m.version not in recorded]
            raise RuntimeError(
                "Schema migration history has gaps"
                + (f": {', '.join(missing)}" if missing else "")
            )
        for migration in plan[:applied_count]:
            if recorded[migration.version] != migration.checksum:
                raise RuntimeError(f"Schema migration checksum drift: {migration.version}")

        for migration in plan[applied_count:]:
            async with connection.begin():
                await _set_local_step_timeouts(connection)
                await migration.apply(connection)
                await migration.verify(connection)
                await connection.execute(text("""
                    INSERT INTO agency_schema_versions (version, checksum)
                    VALUES (:version, :checksum)
                """), {"version": migration.version, "checksum": migration.checksum})

        async with connection.begin():
            await _set_local_step_timeouts(connection)
            for migration in plan:
                await migration.verify(connection)
    finally:
        # Cancellation must neither return a still-locked physical connection
        # to the pool nor leak a checked-out connection. Finish both operations,
        # then propagate the original cancellation.
        original_error = sys.exc_info()[1]
        cleanup_task = asyncio.create_task(_close_runner_connection(
            connection, lock_acquired=lock_cleanup_required,
        ))
        try:
            await asyncio.shield(cleanup_task)
        except BaseException:
            try:
                await cleanup_task
            except BaseException:
                if original_error is None:
                    raise
            if original_error is None:
                raise

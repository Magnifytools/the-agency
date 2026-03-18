"""
Offline DB initialization: DDL migrations, seed data, and cleanup.

Run separately from the web process:
    python -m backend.scripts.init_db

Safe to run multiple times — all operations are idempotent.
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_init():
    """Execute all DDL, seed, and cleanup operations."""
    # Import the functions from main — they are already defined there
    from backend.main import (
        _schema_needs_startup_ddl,
        _ensure_columns,
        _ensure_numeric_types,
        _ensure_columns_v2,
        _ensure_columns_v3,
        _ensure_columns_v4,
        _ensure_columns_v5,
        _ensure_columns_v6,
        _ensure_columns_v7,
        _ensure_columns_v8,
        _ensure_columns_v9,
        _ensure_columns_v10,
        _reset_admin_password,
        _seed_national_holidays,
        _cleanup_qa_test_data,
        _ensure_categories,
        _seed_recurring_templates,
        _generate_recurring_instances,
        _backfill_module_permissions,
    )

    logger.info("=== Starting offline DB initialization ===")

    # DDL migrations
    if await _schema_needs_startup_ddl():
        logger.info("Running DDL migrations (schema not yet up to date)...")
        await _ensure_columns()
        await _ensure_numeric_types()
        await _ensure_columns_v2()
        await _ensure_columns_v3()
        await _ensure_columns_v4()
        await _ensure_columns_v5()
        await _ensure_columns_v6()
        await _ensure_columns_v7()
        await _ensure_columns_v8()
        await _ensure_columns_v9()
        await _ensure_columns_v10()
    else:
        logger.info("Schema up to date, skipping DDL migrations.")

    # One-time admin password reset
    await _reset_admin_password()

    # Seed data
    await _seed_national_holidays()
    await _ensure_categories()
    await _seed_recurring_templates()
    await _generate_recurring_instances()

    # Backfills
    await _backfill_module_permissions()

    # Cleanup
    await _cleanup_qa_test_data()

    # Encrypt any legacy plaintext Discord secrets
    try:
        from backend.scripts.encrypt_discord_secrets import migrate as encrypt_discord
        await encrypt_discord()
    except Exception as e:
        logger.warning("Discord secret encryption skipped: %s", e)

    logger.info("=== Offline DB initialization complete ===")


def main():
    asyncio.run(run_init())


if __name__ == "__main__":
    main()

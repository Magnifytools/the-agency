"""Explicit schema-only release command: python -m backend.scripts.migrate."""
import argparse
import asyncio
import logging

from backend.db.database import engine
from backend.startup.schema_baseline import (
    EXPECTED_SCHEMA_VERSION, check_deployment_ready, migrate_schema,
)


async def run(*, check_only=False):
    try:
        if not check_only:
            await asyncio.wait_for(migrate_schema(engine), timeout=300)
        await asyncio.wait_for(check_deployment_ready(engine), timeout=10)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only schema/version verification")
    args = parser.parse_args()
    try:
        asyncio.run(run(check_only=args.check))
    except Exception as exc:
        # Do not echo connection strings, SQL parameters or business rows in
        # release output. Failure still exits nonzero and prevents deployment.
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        logging.error("Schema verification/migration failed: %s", reason)
        raise SystemExit(1) from None
    print(f"Schema ready: {EXPECTED_SCHEMA_VERSION}")


if __name__ == "__main__":
    main()

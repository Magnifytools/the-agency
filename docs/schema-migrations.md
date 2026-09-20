# Schema releases

Run `python -m backend.scripts.migrate` with the target database configured before starting the web process. `python -m backend.scripts.migrate --check` only verifies the deployed schema and revision. Both exit nonzero on failure. The command has a five-minute overall limit; verification has a separate short timeout.

Railway runs this command through `deploy.preDeployCommand` before starting the new container. A failed pre-deploy command prevents deployment, as described in [Railway's deployment contract](https://docs.railway.com/deployments/pre-deploy-command). The web lifespan performs verification only and starts background tasks afterward. `/api/ready` returns the application commit and required schema revision; a missing or changed migration record makes it return 503.

## Adoption and supported predecessors

The first canonical release is frozen in `backend/startup/schema_versions/p12.json`. It includes bootstrap SQL, the additive upgrade statements previously run by the web process, enum labels, column contracts and foreign keys. It does not import future ORM definitions to construct old migrations. The artifact's SHA-256 is recorded with each applied step in `agency_schema_versions`.

Supported inputs are an empty database, a complete P12 schema, or an otherwise valid P12 schema lacking the explicitly listed additive columns/tables. Other missing columns, changed keys, incompatible types, nullability, string lengths or numeric precision cause an explicit failure. Historical production variants are named per column. Existing timestamps, financial floats, defaults, optional legacy columns and extra tables are preserved. Adoption of an already complete schema verifies it without running ALTER statements or renaming equivalent indexes.

The old Alembic history has several disconnected roots and assumes pre-existing tables. This release neither replays nor stamps that history. A database containing `alembic_version` requires a separately reviewed adoption path and is rejected. Never use a blanket stamp, `init_db`, legacy seeds, deduplication or cleanup as a deployment substitute.

## Transactions and recovery

A session advisory lock serializes migration processes across the entire release on one connection. Each step commits its SQL, verification and ledger row together. Enum changes have a separate step because PostgreSQL requires a commit before newly added labels can be used. A failed schema step can therefore leave the verified enum step recorded; rerunning continues the same known prefix. Unknown versions, gaps or checksum changes are rejected.

Uniqueness conflicts block migration. The command never chooses which duplicate timer, daily or recurrence to delete. A failed verification also blocks web startup. A canceled migration rolls back its current step; the lock is released or the physical connection is invalidated before returning to the pool.

Before production rollout, exercise bootstrap, supported predecessor upgrades, repetition, concurrent execution and deliberate failure in a disposable database. Preserve a restorable backup using the database platform's existing backup process. The P12 transition is additive and compatible with the preceding application binary. If deployment verification fails, retain that previous binary and investigate the failed step. Do not run automatic destructive downgrades; data restoration, if ever necessary, is a separate reviewed operation.

## Future changes

Keep published artifacts immutable. Add a new ordered migration and its contract, rather than editing P12 SQL or its checksum. Every field must have a real reader and writer. Update the expected revision, preflight compatibility and tests together. Preserve source records and attribution; historical data correction needs its own explicit review.

The migration ledger is an operational contract consumed by release verification and readiness. It does not replace delivery receipts, command receipts or the business change journal.

The contract verifies all 29 ORM uniqueness rules plus the active-timer partial index by their keys and predicates, independently of their names. It preserves the stronger historical holiday index using `COALESCE`. Two missing historical constraints are added explicitly: balance snapshot date and monthly close year/month. Duplicate keys prevent the transaction from committing; no financial rows are consolidated or changed.

## Current composed plan

P14 adds `schema_versions/job_runtime_v1.json` through `startup/deployment_schema.py`. It creates only the job runtime table, then verifies its columns and primary key. The published P12 artifacts and checksums remain unchanged; their migration records and application timestamps are preserved.

The DDL is additive, but an older binary with an exact older ledger check does not accept the new revision on a fresh startup. Do not blindly redeploy that binary after the new ledger commits. Use a forward fix or a reviewed binary that recognizes the current schema contract; do not delete migration records to bypass readiness.

# Automation execution contract

Automations remain disabled by the existing `automations` capability. Every event hook enters `execute_automations`, which checks the capability before querying rules or committing. This does not activate a router, screen or scheduled job.

Conditions require a present, non-null event value for every configured key. Lists retain their existing any-match meaning. An absent condition field does not broaden a rule's scope.

`daily_check` has no event producer and is no longer offered or accepted for new rules. Existing rows remain readable and deletable; they may be disabled, but cannot be reactivated until changed to a supported trigger. No historical row is rewritten.

Each action runs inside a database savepoint. A constraint failure rolls back its mutations and records an error while subsequent rules can continue. The final commit persists action changes, rule counters and logs. Exceptions are recorded by class, not raw transport/SQL text that could expose credentials.

Execution logs expose `outcome: success | skipped | error`. `success` is true only for success. Missing targets/configuration are skipped; a Discord non-2xx response is an error with `sent: false`. Historical skipped/failed-delivery results are interpreted truthfully when read, without rewriting stored logs. A mismatch in conditions creates no execution record or run-count increment.

Task creation shares the normal TaskCreate schema and task scope validator. Task state changes share `stamp_task_status` with create, update and bulk API paths: first completion records naive UTC, repeated completion preserves its date, reopening clears it, and advanced status maintains its existing day marker. Assignment/notification recipients must be active users; notifications use the existing notification service.

## Verification

The baseline backend suite passed 595 tests with two credential-dependent skips. The expanded suite passed 621 tests with the same two skips, using a dedicated local PostgreSQL database. The initial 26 new cases cover all supported event gates, missing conditions, real task-hook behavior, real FK rollback and continuation, hierarchy inference/rejection, state dates, unsupported triggers, and simulated Discord 204/429/503 responses. Four additional default-capability and historical-result checks also pass (30 focused tests total). Frontend: 71 tests pass with one worker, production build passes, and the three outcome states were inspected in a local browser with fixture data. A first parallel frontend run encountered worker startup timeouts; the bounded rerun passed. No external delivery was performed.

## Remaining boundaries

This is not a general command bus or a delivery outbox. External HTTP cannot be rolled back with SQL; durable retries, event deduplication, permission/delegation policy for rule creators, shared services for all project/insight operations and a unified frontend/backend capability manifest remain separate work. The existing overdue job may still scan tasks while the engine is disabled. Historical task dates are not backfilled.

Savepoint-aware Undo is described in [Undo transactions](undo-transactions.md). Nested actions are recorded only after the outer commit, while rolled-back action mutations are discarded. Automations remain disabled by the existing capability; this correction does not authorize enabling them.

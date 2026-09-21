# Progress

- Contract and active routes reviewed.
- DTO/error contract sent to root.
- Recoverable individual, cohort and tone generation implemented with actor-scoped keys.
- Provider calls run outside database transactions; final ACL, policy and source snapshots are revalidated under ordered advisory locks.
- Generated assertions carry validated source keys; human edits lose inherited certification when their text changes.
- Nine focused PostgreSQL/API recovery tests pass, including concurrent replay, timeout, revocation and a source mutation during provider execution.
- Broad directed reporting suite passes: 56 tests.
- Frontend recovery now covers individual, cohort and tone operations with per-user durable keys, same-key retry, reload recovery and fail-closed storage handling.
- The digest editor renders assertion sources, explains legacy versions and clears source keys as soon as a person edits an assertion.
- Directed frontend regression: 49 tests across six files; production build passes. Full suite is being repeated in one worker after unrelated five-second timeouts were traced to two old polling previews competing for local CPU.
- Final frontend tree: 434 tests across 69 files pass in one worker, 27 focused recovery/permission tests pass, and the production build succeeds. P26/main merged cleanly as `7849aac`; no product conflict.

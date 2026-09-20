# Progress

- Contract and active routes reviewed.
- DTO/error contract sent to root.
- Recoverable individual, cohort and tone generation implemented with actor-scoped keys.
- Provider calls run outside database transactions; final ACL, policy and source snapshots are revalidated under ordered advisory locks.
- Generated assertions carry validated source keys; human edits lose inherited certification when their text changes.
- Nine focused PostgreSQL/API recovery tests pass, including concurrent replay, timeout, revocation and a source mutation during provider execution.
- Broad directed reporting suite passes: 56 tests.

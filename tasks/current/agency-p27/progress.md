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
- Post-merge backend full suite: 1,369 passed, 2 skipped with isolated PostgreSQL. Browser preview on `agency_phase27_preview_20260921` recovered an existing generation key after a simulated lost response without creating another version; the editor showed task/project sources, removed certification when a title was edited, and identified an older version without sources. Desktop 1280 and mobile 390 had no overflow or console errors. This preview did not call the external provider or modify production.
- Draft PR39 opened and attached. The merged-tree frontend suite passed 441 tests and the build; the initial CI run passed all six checks. The final source-revalidation patch needs its own exact-head gate before publication.
- Review found that individual/cohort generation did not revalidate collected facts after the provider call. Canonical source-snapshot comparison and PostgreSQL regressions were added before the final gate.
- Final source snapshots are now recollected and hashed under the generation and coverage locks. A mismatch returns `sources_changed` (409); the frontend keeps that key so the exact intent can recollect fresh facts and retry. PostgreSQL recovery tests (11) and the focused frontend recovery test (3) pass.
- The provenance-spoof and source-catalog ACL review findings are closed in `539aa8b`, with creator/responsible API coverage.
- Source provenance now comes only from the prior durable assertion. Response contexts re-check module reads once per request, project tasks/groups and legacy facts by module, and keep stored contexts unmodified for server regeneration. The focused PostgreSQL/API digest suite passes 30 tests.
- Final local frontend run over 70 files had 441 passes and one five-second timeout in an unchanged QuickCapture test; that file passed 16/16 on isolated rerun. Exact-head backend full and CI are the release gates; the frontend full suite will be repeated with a longer test timeout on this busy workstation, without changing project test configuration.

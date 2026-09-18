# Legacy scheduled-producer pause

`LEGACY_SCHEDULED_COMMUNICATIONS_ENABLED` defaults to `true`, preserving existing
behavior. When false, startup does not register morning/evening, weekly report,
meeting alert or Google sync loops. Manual Google synchronization returns a clear
409 and preserves the connection. OAuth can still store a successful connection;
it does not perform an initial sync. The old extension upcoming endpoint returns
an empty list while paused, so desktop producers also stop during the transition.
The manual delivery worker and unrelated domain jobs are unaffected.

This is a rollout bridge, not a replacement for draining old revisions:

1. Deploy this bridge with the default true; verify read-only health and CI.
2. Set `LEGACY_SCHEDULED_COMMUNICATIONS_ENABLED=false` and
   `DELIVERY_WORKER_ENABLED=false`. Restart every serving revision, drain all old
   instances and wait for in-flight inline operations to finish. The settings are
   read by each process; changing environment alone does not interrupt an old loop.
3. Deploy B2 with its new `SCHEDULED_COMMUNICATIONS_ENABLED=false`, run its pure
   migration/readiness checks, then drain the bridge revisions before enabling
   B2 scheduling and B2-compatible delivery workers. No real message is needed
   to verify the transition.
4. Keep the legacy flag false for rollback protection. Do not restore old inline
   senders against new pending occurrences or the new calendar-key schema. A
   rollback must use a compatible producer/consumer version.

No historical data is changed by this bridge, and no new policy is activated.

# Durable manual Discord deliveries

Daily and digest sends now persist an intention before contacting Discord. The
existing daily and digest routes return **202**, `success: false`, `status:
pending`, and a `delivery_id`. Existing generic/team reminders are outside this
change. The digest preview uses the digest endpoint, including its edited text;
it no longer bypasses ownership through the generic custom-message route.

## Contract

- `GET /api/deliveries?source_kind=daily|digest&source_id=…` returns the latest
  receipts for an authorized source; `GET /api/deliveries/{id}` returns one.
- `POST /{id}/retry` retries a confirmed failure, preserving already confirmed
  parts. A 429 retains its retry delay. Changed ordinary drafts must be reviewed
  and queued from their editor again.
- `POST /{id}/cancel` cancels only pending intentions, preserving the draft.
- `POST /{id}/resend` accepts `reviewed: true` plus a stable `review_key`. It is
  available only for uncertain deliveries. It creates a new intention containing
  exactly the reviewed original text, even if the current draft has changed.
  Repeating that key returns the same intention. A second distinct resend of
  the same uncertainty is rejected; inspect the first replacement's receipt.

`sent` means all required message parts have provider receipts. Headers alone do
not count. `failed` means the provider rejected a part or no connection was
established. `uncertain` means acceptance cannot be excluded. An expired lease
is uncertain, never automatically retried. Only a current matching daily version
is marked sent; an older snapshot's receipt does not overwrite a newer draft.
Missing AI output uses the complete raw text, split into message parts.

Each delivery records source/content hashes, initiating actor, destination
fingerprint, immutable text, timestamps and state. Each numbered attempt stores
its claim token, lease, and real part states/Discord IDs. The UI reads those same
parts, exposes the reviewed text, and distinguishes paused, rejected and uncertain
deliveries. Reading, retrying and cancelling require source access; dispatch
revalidates active actor, permission, ownership, source version and destination.
Queue workers do not impersonate an admin or inherit a request's Undo actor.

The service uses short PostgreSQL row locks with `SKIP LOCKED`. No transaction is
held across HTTP. A token prevents a late response from replacing a recovered
attempt. Provider HTTP timeout is shorter than the lease. Locks cannot cancel
external effects: no exactly-once guarantee is claimed. A provider success followed
by a failed receipt commit leaves an in-flight record that becomes uncertain;
it is never replayed automatically. A partially confirmed attempt exposes its
known IDs; uncertainty without an ID requires checking Discord before resending.

## Deployment and rollback

1. Deploy this revision with **`DELIVERY_WORKER_ENABLED=false`** (the default).
   The new routes durably queue only; the UI explicitly shows processing paused.
   Schema creation is additive and serialized by a PostgreSQL advisory lock.
   `/api/ready` checks the tables, columns and unique indexes. Do not invoke the
   historical `init_db` script or its seeds/cleanup as a migration.
2. Drain/stop every previous revision's web instance and allow its outstanding
   daily/digest requests to finish. Cached digest previews that still call the
   generic custom-message route receive 409 with a reload instruction, before
   settings resolution or provider HTTP. The route requires the explicit
   `X-Agency-Send-Intent: custom-v1` contract supplied only by the current custom
   message client; this version marker is not an authorization boundary, and
   admin permission remains required. No global tab reload is a rollout prerequisite.
   The current generic admin sender also uses the ledger; see the B1 rollout requirements in manual-communications.md.
   Old server-side direct senders do not understand the new
   dedupe key. Do not run them alongside an enabled new worker. Do not enqueue
   duplicate operational test messages to verify rollout.
3. Check readiness, existing draft counts, queue/receipt reads and permissions.
   Set **`DELIVERY_WORKER_ENABLED=true`** and deploy/restart the new revision.
   Its lifespan starts the real `manual-deliveries` loop; multiple new workers
   are supported. Confirm configured flag via an authorized receipt response and
   inspect naturally requested deliveries for pending→sending→sent receipts.
   No automatic historical backfill or resend is performed.
4. To pause/rollback processing, set the flag false and drain current new workers.
   Preserve tables and receipts. Restore a revision that understands the ledger;
   reverting to a direct-sender revision is unsafe while queued/uncertain intents
   exist. Do not rewrite uncertain rows to pending or purge dedupe keys as a
   cleanup operation. Pending intentions expire after 24 hours; a user's fresh
   review/queue request can renew an expired intention without changing its ID.

The worker flag is a deployment control, not a message-sending permission. Quiet
hours, recurring reminder scheduling and unified incidents belong to the next
delivery and are not implemented here. Manual sends remain explicit user actions.
Historical `sent` flags do not acquire invented provider receipts.

## Verification

Real PostgreSQL regression tests live in
`backend/tests/integration/test_deliveries.py`; all provider effects use
`httpx.MockTransport`. Coverage includes concurrent producers/consumers, partial
thread failures, rate limits, restart/lease fencing, failed commits before and
after provider acceptance, revoked permissions, source edits during delivery,
ownership, raw-text preservation, 202 compatibility, and additive schema upgrade
from tables absent. Frontend DOM regressions exercise receipts, uncertainty review,
raw dailys and the digest preview's linked endpoint.

Run against a dedicated local `TEST_DATABASE_URL` with `REQUIRE_TEST_DATABASE=1`;
the integration harness refuses remote or application databases. Never use a
real Discord destination for automated verification.

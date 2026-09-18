# Durable manual communications

Manual PM briefings, weekly reports, daily-summary aliases, custom messages and
explicit connection tests now use the same delivery worker as daily/digest sends.
No scheduled producer or hidden module is enabled by this change.

## Sources and authorization

`communication_requests` is an immutable manual snapshot with an owner, kind,
scope, civil period, title, full content and destination type. It is a real
`source_kind=communication` source for `deliveries`; no placeholder source IDs
are used. The source key prevents identical repeated requests from creating
multiple intentions. A new text cannot bypass an earlier sending/uncertain
intention for the same owner, kind, scope and period. Pending older text is
cancelled when the user submits a revised snapshot.

The source registry rejects unknown kinds. PM personal requests require the
owner's current PM permission; team PM and every other manual kind require an
active administrator. Read/write permissions are checked separately, and a
member cannot read another person's request by guessing its ID. The worker
revalidates source ownership, permissions, scope, content hash and destination
before each provider step. No worker impersonates an admin.

`stage_request` and `stage_delivery` do not commit. Their caller commits the
source and delivery together before returning 202; rollback leaves neither.
There are no provider calls during staging. HTTP receipts expose the stored
snapshot and preserve the text if preparation or sending fails.

## API and compatibility

The existing manual POST routes return 202 plus `DeliveryReceipt`:

- `/api/pm/briefing/discord?scope=mine|team`
- `/api/discord/send-weekly-report?week_start=YYYY-MM-DD` (Monday)
- `/api/discord/send` and `/api/discord/send-daily-summary` (same source/intent)
- `/api/discord/send-custom`
- `/api/discord/test-webhook`

A queued result has `success:false`, `status:pending` and a `delivery_id`, never
premature success. The legacy `/send` alias also has truthful `ok` and `date`.
`GET /api/deliveries/manual?kind=…&scope=…` returns recent requests owned by the
current actor. Existing source lists and receipt/cancel/retry/reviewed-resend
routes also work with communication sources. The frontend reads these histories
after reload, shows the destination, full text and per-part outcomes, and uses
receipt status for its messages.

The PM preview returns `discord_content`. Current clients submit exactly that
text and its civil `date`, preserving the reviewed snapshot across midnight.
Legacy clients without a preview receive a deterministic briefing without a new
AI call per send. PM planning follows Hoy: deadlines today plus work scheduled today without an
overdue deadline, in the business zone. Recurring templates are excluded;
overdue deadlines appear in their separate section. Weekly manual and scheduled rendering
share one reader accepting an explicit inclusive civil interval; a current-week
manual report is a snapshot at request time, not a claim the week has finished.

The existing `X-Agency-Send-Intent: custom-v1` gate remains required for custom
messages. Old cached digest clients receive 409 before destination resolution.
This is a protocol marker, not authorization.

Connection tests support `X-Agency-Request-Key` (16–80 characters). A lost API
response is retried with the same key, including after midnight or configuration
changes; the existing receipt is returned without another send. The UI retains
the key on error and renews it only for a new click after receiving a receipt.
A new explicit test may run after a confirmed previous result; uncertain prior
sends still require receipt review. Legacy callers without a key deduplicate the
same test within the civil day. Reusing a request key with different text or
scope returns 409; it cannot silently substitute another intention. Identical
custom text already sent that day returns its existing receipt with an explicit
“already confirmed, not sent again” message. Tests are manual communications, never a side
effect of readiness, a settings read or deployment verification.

## Provider behavior

Webhook messages use `wait=true` and the existing multipart receipt protocol.
Weekly owner DMs add a separately confirmed channel-open step and message parts.
A channel ID is not a message ID and opening a channel does not mark the delivery
sent. Confirmed channel/prefix parts survive a retry of a rejected later part.
Timeout, lost response, an expired lease or receipt-commit failure becomes
uncertain; it does not trigger an automatic repeated message. There is no
fallback from a partially delivered thread/DM to another sender.

The configured global Discord owner is only the existing manual weekly-report
destination. It is not used as another user's personal Discord identity. No new
personal DM mapping, email channel, preference or cadence is created here.

## Schema, rollout and rollback

The additive schema function creates `communication_requests` under the existing
migration lock. Readiness verifies its columns and actual unique request-key
index. Upgrade tests begin with that table absent. Do not invoke legacy seed or
business-data cleanup scripts.

1. Pause `DELIVERY_WORKER_ENABLED` on **all existing A revisions before deploying
   B1** and drain those workers. An old worker does not understand communication
   sources and must not claim them. Old manual inline HTTP requests must finish.
2. Deploy B1 with the flag false. New manual POSTs persist their intentions and
   receipts honestly show paused processing. Confirm schema/readiness and source
   authorization; no real provider test message is needed.
3. Drain all older server revisions, then enable the worker on B1. Verify queued
   naturally requested communications through receipts. Never run old inline
   senders alongside the new consumer and assume the new keys deduplicate them.
4. To roll back, pause producer traffic/worker and drain in-flight work. Preserve
   sources, receipts and keys. Return only to a revision that understands these
   sources; do not resume A-only workers or restore direct senders while B1 rows
   can be pending, sending or uncertain.

This is B1 only. Reminder/meeting/weekly jobs retain their existing scheduling
and transports until B2; the shared weekly *reader* does not migrate its cron
sender. Hidden automations remain gated and require a later transactional event
contract. Unified incidents, snooze/resolution, per-client reporting cadence and
cross-device notification delivery are also outside this change.

## Verification

`backend/tests/integration/test_manual_deliveries.py` uses a dedicated local
PostgreSQL database and simulated providers, with real network transport blocked.
It exercises staging/commit failure, concurrent producers/workers, identity and
scope changes between parts, multipart DM receipts, uncertain outcomes, aliases,
connection-test replay, source ownership, business midnight and schema upgrade.
The existing daily/digest delivery and PM/reporting tests run alongside it.
Frontend DOM/API tests cover receipts, reviewed PM content, request keys and
error recovery. No automated verification sends a real Discord message.

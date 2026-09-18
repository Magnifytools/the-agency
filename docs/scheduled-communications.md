# Opt-in scheduled communications (B2)

The scheduler prepares durable occurrences for morning plans, evening recaps,
weekly team reports and timed meetings. It never calls Discord. Remote messages
use the delivery ledger; local app notifications and occurrence state commit
atomically. Hidden automations, incident management and new personal Discord
identity linking are outside this change.

## Actual preferences and ownership

`GET /api/communication-schedules` returns a catalog even when no policy exists.
Missing policies are `needs_review`, not enabled. `PUT /{kind}` requires an
explicit enabled/channel selection and the current revision; conflicts return
409 without overwriting another save. Historical reminder times and preference
JSON are suggestions/history, never consent. Google OAuth no longer enables
meeting notifications as a side effect.

Personal policies belong to the authenticated user. Morning/evening require task
read access and offer in-app delivery or an explicitly chosen shared team
webhook. Meetings offer in-app and extension notifications. A personal Discord
DM is unavailable until a verified identity-linking flow exists; there is no
fallback to a global recipient. The weekly team policy is a singleton assumed
explicitly by an active administrator. Its `destination_id` is a technical
Discord recipient, visibly entered by that administrator, not a User mapping.

The settings panel reads and writes the actual policy and shows blocked reasons,
scheduler pause, occurrence history and remote receipts. Admin-only limited
configuration endpoints store webhook/bot credentials using existing vault
cipher/storage and return only configured booleans. Saving never sends a test
message. Removed legacy auto-send controls retain their historical data.

## Identity and transactions

`communication_schedules` stores only effective preferences. A persistent
`communication_occurrences` key identifies person/type/channel/civil day, a
closed weekly period, or person/event/start-time revision/channel. The key does
not change when the message text or configured hour changes. Re-enabling a policy
starts at its new effective time; historical periods are not replayed.

The planner uses unique-key upserts. Preparation locks an occurrence and its
policy, queries local domain data, then inserts the immutable request plus
Delivery (or app Notification) in one transaction. No lease is needed for local
preparation. Preparation errors are visible as blocked without retaining a
half-created request. DeliveryAttempt retains the existing external-send lease,
fencing and uncertainty semantics. Every remote part rechecks active actor,
permission, policy, source event, recipient and content/destination fingerprints.
A revoked policy cancels remaining parts. Quiet hours/paused scheduling defer
pending parts while preserving confirmed prefixes. No uncertain part is retried
automatically.

`ready` means prepared, not sent. `local_delivered` means available in the app,
not read. Extension availability does not claim desktop presentation. Existing
`Event.alert_sent_at` is treated as a legacy unverified receipt and is not a
reason to replay an alert.

## Time and windows

Instants are stored as naive UTC; civil dates and Event start times use the
configured business zone. Missing DST times advance to the first valid minute;
a repeated time uses its first occurrence and the civil key prevents duplicates.
Silence spanning midnight is supported. If silence ends beyond expiry, the
occurrence expires visibly.

Morning plans use planned/due/overdue work and include meetings even without
tasks. Evening recaps use completion timestamps and civil time-entry periods;
a pending task is not described as untouched, and a missing daily is described
as not saved. Morning expires at the configured evening slot (18:00 fallback);
evening expires at civil midnight. Weekly reports cover the preceding closed
Monday–Friday, are due Saturday 08:00 and expire Monday 08:00. A delayed run uses
the stored period. Meeting windows run from configured advance notice to start;
all-day entries do not have a timed reminder.

## Calendar ingestion

Google responses are fully paginated, including cancellations. A page failure,
malformed response or missing credential raises an error and preserves saved
events. A successful full window reconciles only the authenticated user, the
selected source calendar and `source=google`; manual/other-calendar/out-of-window
rows remain untouched. A per-user advisory transaction lock prevents two delayed
syncs from overwriting each other. Credentials/connection are rechecked before
writes. Offset timestamps normalize into the business civil zone.

The additive `source_calendar_id` and scoped unique index replace the old global
external-ID uniqueness while preserving Event IDs. Existing unscoped rows are
not assigned a calendar by inference: a successful provider match can adopt one;
unverified legacy rows cannot produce a timed alert. Cancelled scoped rows are
removed by reconciliation, which invalidates their pending occurrences.

The implementation follows Google's [Events.list contract](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
for `nextPageToken`, `showDeleted` and explicit RFC3339 offsets. `primary` remains
the existing per-user calendar selector; this does not add a multiple-calendar
management interface.

## Extension contract

Version 2.2.0 or later uses `/extension-upcoming`, which returns only currently
eligible own occurrences, effective preferences, the scheduler flag, and update
metadata. Old `/api/calendar/upcoming` returns an empty list because those
clients ignore preferences and silence. The app explains this requirement and
links the actual packaged-extension endpoint. The release must package the new
extension before claiming that the download provides this capability.

The extension adapter is an independent companion change: stable notification
IDs and persistent per-user/per-occurrence installation storage retain pending,
confirmed and uncertain outcomes across restarts. A read of the endpoint is
never an acknowledgment. Dedupe is per installation; no cross-device exactly-once
claim is made.

## Deployment and rollback

1. First deploy the [legacy pause bridge](scheduled-rollout-bridge.md). Set
   `LEGACY_SCHEDULED_COMMUNICATIONS_ENABLED=false` and `DELIVERY_WORKER_ENABLED=false`,
   restart every serving revision and drain all old instances/inline sends. The
   earlier delivery-worker flag alone cannot pause legacy producers.
2. Deploy B2 with `SCHEDULED_COMMUNICATIONS_ENABLED=false`. This also pauses
   automatic and manual Google synchronization during the calendar key migration;
   existing calendar data remains readable. Run only the pure schema migration
   and readiness checks, never seeds or real provider test messages.
3. Readiness verifies the new tables, columns and unique-index semantics. The
   calendar upgrade adds its scoped index before removing the old single-column
   unique constraint. No events are deleted or arbitrarily reassigned by DDL.
4. Drain all old revisions, install/package the 2.2.0 extension companion change,
   then enable the new scheduler and B2-compatible delivery workers. Enabling the
   scheduler does not create consent: every policy remains unconfigured until
   explicitly saved. Observe naturally requested deliveries through receipts.
5. Rollback pauses producers/workers and preserves sources, keys, events and
   receipts. Do not resume old inline senders or old calendar writers against
   the scoped-ID schema; return only to a compatible revision.

Tests use a dedicated PostgreSQL database and simulated transports with real
network blocked. They cover concurrent planners, rollback, delayed runs, expiry,
DST/silence, permission/recipient changes, per-part deferral, actual policy API,
calendar pagination/reconciliation and schema upgrade from the old unique key.

## Restart freshness and preference changes

Google meeting occurrences require a complete committed reconciliation of the
current connected calendar after the worker process started, no older than 20
minutes. `users.google_calendar_synced_at` is written in the same transaction as
the reconciled events, cleared on reconnect/disconnect, checked before preparing
or exposing each Google meeting, and displayed by Calendar settings as the last
complete sync. Failed pages or failed commits never advance it. The sync loop
runs immediately on startup, then every 15 minutes. Manual meetings do not
require a Google connection or this freshness check. Blocked occurrences expose
a reason in Avisos and can recover after a successful sync within their window.

Changing meeting lead time or re-enabling the policy updates the due time of
unconsumed/extension-ready occurrences while preserving their identity. This
lets an installation that has not shown the alert use the new due time; the
extension's durable confirmed/uncertain state prevents another presentation on
an installation that already handled that identity. In-app delivered rows are
never reset. First consent can cover a still-upcoming meeting whose nominal
lead time has passed; past meetings are not backfilled. The extension start time
is derived from the event's civil start, separately from the expiry field.

## Expired Google authorization

A structured `google.auth.exceptions.RefreshError` whose provider response has
`error=invalid_grant` marks the current credential unusable. The update locks and
rechecks the same user, encrypted token and calendar identity, so a delayed
failure cannot disable a newer OAuth connection. Events, retained credentials
and the last successful synchronization timestamp are preserved. Other errors,
including timeouts and unstructured error strings, do not disconnect the user.

No migration or additional stored field is required. Existing
`google_calendar_connected=false` plus a retained refresh token means
`connection_status=reconnect_required`; an explicit disconnect removes the
credentials and produces `disconnected`. Connected authorization produces
`connected`. These API states drive Calendar settings, which offers reconnection
and refreshes after sync failures. A successful signed callback for an active
user restores the connected flag and clears synchronization freshness until a
new full sync succeeds. The scheduler skips disconnected grants; Google meeting
occurrences explain that reconnection is needed, while manual meetings remain
independent. Provider response bodies and OAuth exception messages are not logged.

The state change occurs on the next attempted sync; deployment does not inspect,
refresh or remove credentials. A missing last-sync timestamp alone is never
classified as expired authorization.

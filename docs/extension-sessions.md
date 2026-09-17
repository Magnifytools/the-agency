# Extension session isolation

Popup requests capture both token and a monotonic session epoch. Reads and mutations check ownership after fetch/JSON and before success, error or finally updates. This covers list pagination, Inbox capture/count, task creation/completion, timer state/actions/budgets, manual time and quick creation. Delayed UI callbacks belong to their originating session and are cancelled when it ends.

Logging out clears account-specific lists, timer state and pending controls. An old pending operation cannot release the new account's pending guard. Capture and direct task creation also reject duplicate submissions while pending. Capture listeners are attached once, independently of login/view changes.

Unsent form drafts are retained only in popup memory, keyed by authenticated email, and restored on reconnecting that same account. They are not exposed to a different account and disappear when the popup closes. Restored assignments wait for the existing paginated selector refresh; unavailable assignments remain visibly blocked.

Popup storage writes are serialized, so a pending logout removal completes before a newer login writes its token. Login responses have attempt ownership as well. The background worker compares the currently stored token before displaying delayed notifications, counts or meeting reminders. It no longer removes credentials in response to a capture HTTP 401; the popup owns expiry handling.

This protects local session/UI ownership. It does not cancel or undo a mutation already accepted by the server, provide offline persistence, or add cross-device idempotency. Package version, signing key and distribution artifacts are unchanged by this source commit.

Validation uses mocked DOM/Chrome/network APIs only. The original 14 pagination/capture tests pass, plus cases covering two-account delayed capture success/401/network failure, delayed timer JSON/stop, same-token epoch reuse, account-specific draft restoration, duplicate listener prevention, serialized token storage, and stale background capture/badge/meeting results. No production request or real notification is made.

Verification result: 29/29 extension tests pass (14 original and 15 new). Seven bounded regressions failed against the original source and pass with the change. A local Chrome popup smoke check with all auth/API calls mocked rendered successfully. Node syntax checks and git diff whitespace checks pass.

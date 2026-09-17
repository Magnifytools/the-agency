# Undo and nested transactions

The journal captures one user action per confirmed outer SQLAlchemy session transaction. Releasing a savepoint no longer emits a journal entry: its changes may still be rolled back by the parent transaction. A savepoint rollback removes only operations captured inside that savepoint and restores the prior manual-time capture flag. Successfully released inner savepoints remain subject to their parent rollback.

Implementation uses public SQLAlchemy transaction events and attributes. `after_transaction_create` snapshots the pending operation count when `transaction.nested` is true. `after_commit` dispatches only outside nested transactions. `after_soft_rollback(previous_transaction)` restores the appropriate checkpoint; internal flush rollback events do not erase outer work. Ending a root transaction also clears pending state, including `Session.close()` without a commit.

References: [SQLAlchemy transaction events](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_soft_rollback) and [SAVEPOINT behavior](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#using-savepoint).

PostgreSQL regressions cover inner commit followed by outer rollback, inner rollback followed by outer commit, committed descendants rolled back by their parent, repeated savepoint updates collapsed into one entry, a real foreign-key failure, manual-time capture flags, and session close/reuse. A separate-session test checks actual committed database visibility. The HTTP bulk update test verifies that two completed tasks produce one Undo entry and that Undo restores both statuses and completion dates.

The existing journal sink remains best effort and asynchronous; this change does not make journal persistence transactional with application writes or add delivery retries. No historical journal entries are rewritten.

Validation: the full backend suite passed 634 tests with two credential-dependent skips. One additional automation/Undo composition case was then added and the focused journal, PostgreSQL Undo and automation suites passed all 57 tests. That case verifies that two successful rules and one real FK failure produce one Undo entry containing only the two committed tasks, and that both tasks can be undone together.

from datetime import date

from backend.services.recurrence import is_due_on, summarize_recurrence


def test_legacy_biweekly_keeps_iso_even_week_calendar():
    assert is_due_on(date(2026, 1, 5), pattern="biweekly", day=0, anchor_date=None)
    assert not is_due_on(date(2026, 1, 12), pattern="biweekly", day=0, anchor_date=None)
    assert not is_due_on(date(2020, 12, 28), pattern="biweekly", day=0, anchor_date=None)  # ISO week 53
    assert is_due_on(date(2021, 1, 11), pattern="biweekly", day=0, anchor_date=None)  # ISO week 2


def test_anchored_biweekly_uses_anchor_week_without_changing_weekday():
    anchor = date(2026, 1, 12)  # ISO odd week
    assert is_due_on(anchor, pattern="biweekly", day=0, anchor_date=anchor)
    assert not is_due_on(date(2026, 1, 19), pattern="biweekly", day=0, anchor_date=anchor)
    assert is_due_on(date(2026, 1, 26), pattern="biweekly", day=0, anchor_date=anchor)


def test_anchored_biweekly_starts_on_first_selected_weekday_after_anchor():
    sunday = date(2026, 9, 20)
    assert is_due_on(date(2026, 9, 21), pattern="biweekly", day=0, anchor_date=sunday)
    assert not is_due_on(date(2026, 9, 28), pattern="biweekly", day=0, anchor_date=sunday)
    assert is_due_on(date(2026, 10, 5), pattern="biweekly", day=0, anchor_date=sunday)

    wednesday = date(2026, 9, 23)
    assert is_due_on(date(2026, 9, 28), pattern="biweekly", day=0, anchor_date=wednesday)
    assert is_due_on(date(2026, 10, 12), pattern="biweekly", day=0, anchor_date=wednesday)


def test_anchored_biweekly_is_literal_across_iso_week_53_boundary():
    anchor = date(2020, 12, 27)  # Sunday before ISO week 53
    assert is_due_on(date(2020, 12, 28), pattern="biweekly", day=0, anchor_date=anchor)
    assert is_due_on(date(2021, 1, 11), pattern="biweekly", day=0, anchor_date=anchor)


def test_daily_is_business_days_and_end_date_is_inclusive():
    summary = summarize_recurrence(
        is_recurring=True, pattern="daily", day=None,
        anchor_date=None, end_date=date(2026, 9, 21), paused=False,
        as_of=date(2026, 9, 19),
    )
    assert summary.state == "active"
    assert summary.next_dates == [date(2026, 9, 21)]


def test_scope_and_pause_states_do_not_offer_dates():
    paused = summarize_recurrence(
        is_recurring=True, pattern="weekly", day=1, anchor_date=None,
        end_date=None, paused=True, as_of=date(2026, 9, 20),
    )
    blocked = summarize_recurrence(
        is_recurring=True, pattern="weekly", day=1, anchor_date=None,
        end_date=None, paused=False, client_active=False,
        as_of=date(2026, 9, 20),
    )
    assert (paused.state, paused.next_dates) == ("paused", [])
    assert (blocked.state, blocked.next_dates) == ("blocked_client", [])


def test_invalid_legacy_rule_is_reported_instead_of_materialized():
    invalid = summarize_recurrence(
        is_recurring=True, pattern="monthly", day=31,
        anchor_date=None, end_date=None, paused=False,
        as_of=date(2026, 9, 20),
    )
    assert invalid.state == "invalid"
    assert invalid.next_dates == []


def test_far_future_anchor_starts_preview_at_anchor():
    anchor = date(2035, 1, 1)
    summary = summarize_recurrence(
        is_recurring=True, pattern="biweekly", day=0,
        anchor_date=anchor, end_date=None, paused=False,
        as_of=date(2026, 9, 20),
    )
    assert summary.next_dates[0] == anchor

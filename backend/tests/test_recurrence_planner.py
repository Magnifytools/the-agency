from datetime import date
import pytest

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


# ── Reglas nuevas, festivos y días de trabajo (28 oct 2026) ──────────────────
from backend.services.recurrence import nominal_dates_for, validate_recurrence_rule, work_date


def test_weekdays_rule_takes_several_days_and_validates_them():
    rule = {"pattern": "weekdays", "day": None, "weekdays": [0, 2]}
    assert is_due_on(date(2026, 11, 2), **rule)  # lunes
    assert not is_due_on(date(2026, 11, 3), **rule)
    assert is_due_on(date(2026, 11, 4), **rule)  # miércoles
    for bad in ([], [5], [1, 1], None):
        with pytest.raises(ValueError):
            validate_recurrence_rule(is_recurring=True, pattern="weekdays", day=None,
                                     anchor_date=None, end_date=None, weekdays=bad)
    summary = summarize_recurrence(is_recurring=True, pattern="weekdays", day=None, anchor_date=None,
                                   end_date=None, paused=False, weekdays=[4, 0], as_of=date(2026, 11, 2))
    assert summary.label == "Cada lunes y viernes"
    assert summary.next_dates == [date(2026, 11, 2), date(2026, 11, 6), date(2026, 11, 9)]


def test_quarterly_follows_calendar_quarters_or_the_start_month():
    rule = {"pattern": "quarterly", "day": 5}
    assert is_due_on(date(2027, 1, 5), **rule)
    assert is_due_on(date(2027, 4, 5), **rule)
    assert not is_due_on(date(2027, 2, 5), **rule)
    anchored = {**rule, "anchor_date": date(2026, 11, 1)}
    assert is_due_on(date(2027, 2, 5), **anchored)
    assert not is_due_on(date(2027, 1, 5), **anchored)
    summary = summarize_recurrence(is_recurring=True, pattern="quarterly", day=5, anchor_date=date(2026, 11, 1),
                                   end_date=None, paused=False, as_of=date(2026, 10, 28))
    assert summary.label == "Cada tres meses, el día 5 (feb, may, ago, nov)"
    assert summary.next_dates == [date(2026, 11, 5), date(2027, 2, 5), date(2027, 5, 5)]


def test_last_business_day_skips_weekends_and_holidays():
    # Octubre 2026 acaba en sábado: el último hábil es el viernes 30.
    assert is_due_on(date(2026, 10, 30), pattern="last_business_day", day=None)
    assert not is_due_on(date(2026, 10, 31), pattern="last_business_day", day=None)
    holidays = frozenset({date(2026, 10, 30)})
    assert is_due_on(date(2026, 10, 29), pattern="last_business_day", day=None, holidays=holidays)
    summary = summarize_recurrence(is_recurring=True, pattern="last_business_day", day=None, anchor_date=None,
                                   end_date=None, paused=False, as_of=date(2026, 10, 28), holidays=holidays)
    assert summary.label == "El último día hábil de cada mes"
    assert summary.next_dates[0] == date(2026, 10, 29)


def test_a_date_on_a_weekend_or_holiday_is_worked_the_next_business_day():
    # 15 de noviembre de 2026 es domingo: se trabaja el lunes 16.
    assert work_date(date(2026, 11, 15), pattern="monthly") == date(2026, 11, 16)
    holidays = frozenset({date(2026, 12, 7), date(2026, 12, 8)})
    assert work_date(date(2026, 12, 7), pattern="weekly", holidays=holidays) == date(2026, 12, 9)
    # La diaria se salta el festivo: si no, el día siguiente tendría dos.
    assert work_date(date(2026, 12, 8), pattern="daily", holidays=holidays) is None
    summary = summarize_recurrence(is_recurring=True, pattern="monthly", day=15, anchor_date=None,
                                   end_date=None, paused=False, as_of=date(2026, 10, 28))
    assert summary.next_dates == [date(2026, 11, 16), date(2026, 12, 15), date(2027, 1, 15)]


def test_two_dates_pushed_onto_the_same_day_are_one_task():
    holidays = frozenset({date(2026, 12, 7)})  # lunes festivo
    rule = {"pattern": "weekdays", "day": None, "anchor_date": None, "end_date": None,
            "weekdays": [0, 1], "holidays": holidays}
    assert nominal_dates_for(date(2026, 12, 8), **rule) == [date(2026, 12, 7), date(2026, 12, 8)]
    assert nominal_dates_for(date(2026, 12, 7), **rule) == []
    # Un fin de semana entre medias tampoco pierde la fecha.
    assert nominal_dates_for(date(2026, 11, 16), pattern="monthly", day=15, anchor_date=None,
                             end_date=None) == [date(2026, 11, 15)]

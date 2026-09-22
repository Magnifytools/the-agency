"""A repeated civil hour must keep its quiet window in both occurrences."""

from datetime import datetime
from types import SimpleNamespace

from backend.services.scheduled_communications import quiet_until


def test_quiet_end_uses_the_current_occurrence_of_the_repeated_hour():
    policy = SimpleNamespace(quiet_start="02:00", quiet_end="02:30")
    assert quiet_until(policy, datetime(2026, 10, 25, 0, 15)) == datetime(2026, 10, 25, 0, 30)
    assert quiet_until(policy, datetime(2026, 10, 25, 1, 15)) == datetime(2026, 10, 25, 1, 30)
    assert quiet_until(policy, datetime(2026, 10, 25, 1, 30)) == datetime(2026, 10, 25, 1, 30)
    assert quiet_until(policy, datetime(2026, 10, 25, 1, 31)) == datetime(2026, 10, 25, 1, 31)


def test_overnight_quiet_end_uses_second_fold_when_needed():
    policy = SimpleNamespace(quiet_start="22:00", quiet_end="02:30")
    assert quiet_until(policy, datetime(2026, 10, 25, 0, 15)) == datetime(2026, 10, 25, 0, 30)
    assert quiet_until(policy, datetime(2026, 10, 25, 1, 15)) == datetime(2026, 10, 25, 1, 30)


def test_spring_gap_still_rolls_quiet_end_forward():
    policy = SimpleNamespace(quiet_start="01:00", quiet_end="02:30")
    assert quiet_until(policy, datetime(2026, 3, 29, 0, 15)) == datetime(2026, 3, 29, 1)

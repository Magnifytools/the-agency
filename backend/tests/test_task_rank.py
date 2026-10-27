"""Mismos casos que frontend/src/lib/task-rank.test.ts: el front predice al servidor."""

import pytest

from backend.services.task_rank import is_rank, rank_between, ranks_for_move, spread_ranks


@pytest.mark.parametrize(("low", "high", "expected"), [
    (None, None, "V"),
    ("V", None, "k"),
    (None, "V", "F"),
    ("V", "W", "VV"),
    ("a", "a1", "a0V"),
])
def test_rank_between(low, high, expected):
    value = rank_between(low, high)
    assert value == expected
    assert (low or "") < value and (high is None or value < high)
    assert is_rank(value)


def test_rank_between_rejects_an_inverted_pair():
    with pytest.raises(ValueError):
        rank_between("k", "V")


def test_spread_ranks_are_ordered_and_never_end_in_zero():
    assert spread_ranks(3) == ["FV", "V", "kV"]
    many = spread_ranks(500)
    assert many == sorted(many) and len(set(many)) == 500 and all(is_rank(rank) for rank in many)


def test_moving_between_ranked_neighbours_touches_only_that_task():
    assert ranks_for_move([1, 2, 3], 3, {1: "F", 2: "V", 3: None}) == {3: "k"}
    assert ranks_for_move([1, 3, 2], 3, {1: "F", 2: "V", 3: "k"}) == {3: "N"}


def test_only_tasks_without_rank_or_out_of_order_get_a_new_one():
    assert ranks_for_move([1, 2, 3], 2, {1: None, 2: None, 3: None}) == {1: "F", 2: "V", 3: "k"}
    assert ranks_for_move([1, 2, 3], 2, {1: "V", 2: "k", 3: "F"}) == {3: "s"}
    assert ranks_for_move([1, 2, 3], 1, {1: None, 2: "V", 3: None}) == {1: "F", 3: "k"}
    assert ranks_for_move([1, 2, 3], 2, {1: None, 2: "V", 3: None}) == {1: "F", 3: "k"}


def test_ordering_a_column_keeps_what_was_already_ordered():
    # 21 ya tenía su sitio en Mi agenda: soltar 13 en su columna no se lo cambia.
    assert ranks_for_move([21, 13, 17, 19], 13, {21: "P", 17: None, 19: None}) == {13: "Y", 17: "h", 19: "q"}


def test_ranks_too_long_are_spread_again():
    low, high = "a" + "0" * 62 + "1", "a" + "0" * 62 + "2"
    assert ranks_for_move([1, 2, 3], 2, {1: low, 3: high}) == {1: "FV", 2: "V", 3: "kV"}

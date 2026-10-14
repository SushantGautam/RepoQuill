"""Tests for miniutil.calc."""

import pytest

from miniutil.calc import Counter, moving_average


def test_counter_starts_at_zero():
    assert Counter().total() == 0


def test_counter_initial_values():
    assert Counter([1, 2, 3]).total() == 6


def test_counter_add():
    c = Counter([1, 2])
    c.add(3)
    assert c.total() == 6


def test_counter_floats():
    c = Counter()
    c.add(0.5)
    c.add(1.5)
    assert c.total() == 2.0


def test_moving_average_basic():
    assert moving_average([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]


def test_moving_average_window_one():
    assert moving_average([1, 2, 3], 1) == [1, 2, 3]


def test_moving_average_window_larger_than_data():
    assert moving_average([1, 2, 3], 5) == [2.0]


def test_moving_average_empty():
    assert moving_average([], 3) == []


def test_moving_average_bad_window():
    with pytest.raises(ValueError):
        moving_average([1, 2], 0)

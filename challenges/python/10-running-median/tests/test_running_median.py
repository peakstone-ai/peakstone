import random

import pytest

from solution import RunningMedian


def test_empty_raises():
    m = RunningMedian()
    with pytest.raises(ValueError):
        m.median()


def test_single_value():
    m = RunningMedian()
    m.add(5)
    assert m.median() == 5


def test_running_sequence():
    m = RunningMedian()
    m.add(5)
    assert m.median() == 5
    m.add(1)
    assert m.median() == pytest.approx(3.0)  # avg(1, 5)
    m.add(3)
    assert m.median() == 3                    # middle of [1, 3, 5]
    m.add(3)
    assert m.median() == pytest.approx(3.0)   # avg(3, 3)


def test_even_count_average():
    m = RunningMedian()
    for v in [10, 20, 30, 40]:
        m.add(v)
    assert m.median() == pytest.approx(25.0)  # avg(20, 30)


def test_handles_out_of_order_inserts():
    m = RunningMedian()
    for v in [9, 1, 8, 2, 7]:
        m.add(v)
    # sorted: [1, 2, 7, 8, 9] -> middle = 7
    assert m.median() == 7


def test_negative_and_floats():
    m = RunningMedian()
    for v in [-1.5, 2.5, -3.0]:
        m.add(v)
    # sorted: [-3.0, -1.5, 2.5] -> -1.5
    assert m.median() == pytest.approx(-1.5)


def test_matches_statistics_module():
    import statistics
    rng = random.Random(1234)
    vals = [rng.randint(-100, 100) for _ in range(101)]
    m = RunningMedian()
    seen = []
    for v in vals:
        m.add(v)
        seen.append(v)
        assert m.median() == pytest.approx(statistics.median(seen))


def test_duplicates_allowed():
    m = RunningMedian()
    for v in [4, 4, 4, 4]:
        m.add(v)
    assert m.median() == pytest.approx(4.0)

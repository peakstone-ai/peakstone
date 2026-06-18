import random

from solution import WindowedAggregator

ZERO = {"count": 0, "sum": 0.0, "min": None, "max": None, "mean": None}


def test_empty_and_unknown_group_returns_zero_dict():
    agg = WindowedAggregator(window=10.0)
    assert agg.stats("nope", at=0.0) == ZERO
    agg.add(5.0, "g", 1.0)
    # group exists, but window (90, 100] contains nothing
    assert agg.stats("g", at=100.0) == ZERO
    # still-unknown group
    assert agg.stats("other", at=5.0) == ZERO


def test_basic_single_event_stats():
    agg = WindowedAggregator(window=10.0)
    agg.add(100.0, "g", 4.0)
    s = agg.stats("g", at=100.0)
    assert s == {"count": 1, "sum": 4.0, "min": 4.0, "max": 4.0, "mean": 4.0}


def test_inclusion_at_upper_bound():
    # event exactly at `at` is INCLUDED
    agg = WindowedAggregator(window=10.0)
    agg.add(105.0, "g", 7.0)
    s = agg.stats("g", at=105.0)
    assert s["count"] == 1
    assert s["sum"] == 7.0


def test_exclusion_at_lower_bound():
    # event exactly at at-window is EXCLUDED (half-open lower bound)
    agg = WindowedAggregator(window=10.0)
    agg.add(95.0, "g", 7.0)
    s = agg.stats("g", at=105.0)  # window (95, 105]
    assert s == ZERO


def test_boundary_pair_together():
    agg = WindowedAggregator(window=10.0)
    agg.add(95.0, "g", 1.0)   # excluded
    agg.add(105.0, "g", 3.0)  # included
    s = agg.stats("g", at=105.0)
    assert s == {"count": 1, "sum": 3.0, "min": 3.0, "max": 3.0, "mean": 3.0}


def test_min_max_mean_sum_count_correctness():
    agg = WindowedAggregator(window=100.0)
    values = [3.0, -2.0, 10.5, 4.0, 0.0]
    for i, v in enumerate(values):
        agg.add(float(i), "g", v)
    # timestamps are 0..4; window (4-100, 4] = (-96, 4] covers all of them
    s = agg.stats("g", at=4.0)
    assert s["count"] == 5
    assert s["sum"] == sum(values)
    assert s["min"] == min(values)
    assert s["max"] == max(values)
    assert s["mean"] == sum(values) / len(values)


def test_group_isolation():
    agg = WindowedAggregator(window=10.0)
    agg.add(100.0, "a", 1.0)
    agg.add(100.0, "a", 2.0)
    agg.add(100.0, "b", 100.0)
    sa = agg.stats("a", at=100.0)
    sb = agg.stats("b", at=100.0)
    assert sa == {"count": 2, "sum": 3.0, "min": 1.0, "max": 2.0, "mean": 1.5}
    assert sb == {"count": 1, "sum": 100.0, "min": 100.0, "max": 100.0, "mean": 100.0}


def test_out_of_order_matches_in_order():
    events = [(100.0, 5.0), (95.0, 1.0), (105.0, 3.0), (102.0, 9.0), (98.0, 2.0)]

    ordered = WindowedAggregator(window=10.0)
    for ts, v in sorted(events):
        ordered.add(ts, "g", v)

    shuffled = WindowedAggregator(window=10.0)
    rnd = list(events)
    random.Random(1234).shuffle(rnd)
    for ts, v in rnd:
        shuffled.add(ts, "g", v)

    for at in (95.0, 100.0, 105.0, 110.0, 120.0):
        assert ordered.stats("g", at=at) == shuffled.stats("g", at=at)


def test_duplicate_ts_group_events_all_count():
    agg = WindowedAggregator(window=10.0)
    agg.add(100.0, "g", 2.0)
    agg.add(100.0, "g", 2.0)  # identical (ts, group, value)
    agg.add(100.0, "g", 5.0)  # same (ts, group), different value
    s = agg.stats("g", at=100.0)
    assert s["count"] == 3
    assert s["sum"] == 9.0
    assert s["min"] == 2.0
    assert s["max"] == 5.0
    assert s["mean"] == 3.0


def test_moving_window_includes_and_excludes():
    agg = WindowedAggregator(window=10.0)
    for ts in (90.0, 95.0, 100.0, 105.0, 110.0):
        agg.add(ts, "g", ts)  # value == ts for easy checking

    # at=100 -> window (90, 100]: ts in {95, 100}
    s = agg.stats("g", at=100.0)
    assert s["count"] == 2
    assert s["sum"] == 95.0 + 100.0
    assert s["min"] == 95.0 and s["max"] == 100.0

    # at=105 -> window (95, 105]: ts in {100, 105}
    s = agg.stats("g", at=105.0)
    assert s["count"] == 2
    assert s["min"] == 100.0 and s["max"] == 105.0

    # at=110 -> window (100, 110]: ts in {105, 110}
    s = agg.stats("g", at=110.0)
    assert s["count"] == 2
    assert s["min"] == 105.0 and s["max"] == 110.0

    # at far in the future -> window past all events
    assert agg.stats("g", at=1000.0) == ZERO


def test_stats_is_non_destructive_and_repeatable():
    agg = WindowedAggregator(window=10.0)
    agg.add(100.0, "g", 1.0)
    agg.add(105.0, "g", 3.0)
    first = agg.stats("g", at=105.0)
    second = agg.stats("g", at=105.0)
    assert first == second  # querying must not consume events


def test_exact_keys_present():
    agg = WindowedAggregator(window=10.0)
    agg.add(100.0, "g", 1.0)
    s = agg.stats("g", at=100.0)
    assert set(s.keys()) == {"count", "sum", "min", "max", "mean"}
    assert isinstance(s["count"], int)
    # empty case keys too
    e = agg.stats("g", at=1000.0)
    assert set(e.keys()) == {"count", "sum", "min", "max", "mean"}


def test_float_window_and_timestamps():
    agg = WindowedAggregator(window=1.5)
    agg.add(10.0, "g", 1.0)
    agg.add(10.4, "g", 2.0)
    agg.add(10.5, "g", 3.0)
    # at=11.0 -> window (9.5, 11.0]: all three included
    s = agg.stats("g", at=11.0)
    assert s["count"] == 3
    # at=11.5 -> window (10.0, 11.5]: ts=10.0 excluded (lower bound)
    s2 = agg.stats("g", at=11.5)
    assert s2["count"] == 2
    assert s2["min"] == 2.0 and s2["max"] == 3.0

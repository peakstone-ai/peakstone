# Windowed streaming aggregator

Implement a file **`solution.py`** containing a class `WindowedAggregator` that ingests
timestamped, grouped events and computes aggregate statistics over a sliding time window.

```python
class WindowedAggregator:
    def __init__(self, window: float):
        """window = length of the time window (same units as timestamps)."""

    def add(self, ts: float, group: str, value: float) -> None:
        """Record an event. Events may arrive OUT OF ORDER (ts not monotonic)."""

    def stats(self, group: str, at: float) -> dict:
        """Aggregate the events of `group` whose timestamp is in the half-open
        window (at - window, at] — i.e. at-window < ts <= at."""
```

## Semantics

- The window is **half-open**: an event whose timestamp is exactly `at - window` is **excluded**,
  and an event whose timestamp is exactly `at` is **included**. Formally, an event with timestamp
  `ts` is in the window iff `at - window < ts <= at`.
- **Groups are independent.** `stats` for a group must never observe events recorded under any other
  group.
- **Out-of-order ingestion is allowed.** `add` may be called with timestamps in any order. `stats`
  considers every event added so far regardless of insertion order; calling `add` with the same
  events in a different order yields identical `stats` results.
- **Duplicates count.** Adding the same `(ts, group)` pair (or even the same `(ts, group, value)`)
  more than once records multiple independent events, all of which contribute to the aggregates.
- `stats` returns a dict with **exactly** these keys:
  - `"count"`: `int` — number of events in the window.
  - `"sum"`: `float` — sum of their values (`0.0` if there are none).
  - `"min"`: `float` or `None` — minimum value, or `None` if there are no events.
  - `"max"`: `float` or `None` — maximum value, or `None` if there are no events.
  - `"mean"`: `float` or `None` — `sum / count`, or `None` if there are no events.
- An **unknown group**, or a window that **contains no events**, returns
  `{"count": 0, "sum": 0.0, "min": None, "max": None, "mean": None}`.

## Example

```python
agg = WindowedAggregator(window=10.0)
agg.add(100.0, "cpu", 5.0)
agg.add(95.0,  "cpu", 1.0)
agg.add(105.0, "cpu", 3.0)
agg.add(100.0, "mem", 50.0)   # different group, ignored by "cpu" stats

# Window for at=105, window=10 is (95, 105]:
#   ts=95  is excluded (boundary at-window)
#   ts=100 is included
#   ts=105 is included
s = agg.stats("cpu", at=105.0)
assert s == {"count": 2, "sum": 8.0, "min": 3.0, "max": 5.0, "mean": 4.0}

# Advance `at` so the window (100, 110] only contains ts=105:
s2 = agg.stats("cpu", at=110.0)
assert s2 == {"count": 1, "sum": 3.0, "min": 3.0, "max": 3.0, "mean": 3.0}

# Unknown group:
assert agg.stats("disk", at=105.0) == {
    "count": 0, "sum": 0.0, "min": None, "max": None, "mean": None,
}
```

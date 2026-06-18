from collections import defaultdict


class WindowedAggregator:
    def __init__(self, window: float):
        self._window = window
        # group -> list of (ts, value) pairs, in insertion order.
        self._events = defaultdict(list)

    def add(self, ts: float, group: str, value: float) -> None:
        self._events[group].append((ts, value))

    def stats(self, group: str, at: float) -> dict:
        lo = at - self._window
        count = 0
        total = 0.0
        mn = None
        mx = None
        for ts, value in self._events.get(group, ()):
            if lo < ts <= at:
                count += 1
                total += value
                if mn is None or value < mn:
                    mn = value
                if mx is None or value > mx:
                    mx = value
        if count == 0:
            return {"count": 0, "sum": 0.0, "min": None, "max": None, "mean": None}
        return {
            "count": count,
            "sum": total,
            "min": mn,
            "max": mx,
            "mean": total / count,
        }

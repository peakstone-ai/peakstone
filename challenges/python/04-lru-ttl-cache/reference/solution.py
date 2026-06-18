import time
from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int, ttl: float, now=time.monotonic):
        self.capacity = capacity
        self.ttl = ttl
        self._now = now
        # key -> (value, inserted_at); ordered by recency (oldest first)
        self._data: "OrderedDict[object, tuple]" = OrderedDict()

    def _expired(self, inserted_at: float) -> bool:
        return self._now() - inserted_at >= self.ttl

    def _purge_expired(self) -> None:
        dead = [k for k, (_, ts) in self._data.items() if self._expired(ts)]
        for k in dead:
            del self._data[k]

    def get(self, key):
        if key not in self._data:
            return None
        value, ts = self._data[key]
        if self._expired(ts):
            del self._data[key]
            return None
        self._data.move_to_end(key)  # refresh recency, keep age
        return value

    def put(self, key, value):
        self._purge_expired()
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (value, self._now())
        self._data.move_to_end(key)
        while len(self._data) > self.capacity:
            self._data.popitem(last=False)  # evict least-recently-used

    def __len__(self) -> int:
        self._purge_expired()
        return len(self._data)

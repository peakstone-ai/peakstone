# LRU Cache with TTL

Implement a file **`solution.py`** containing a class:

```python
class LRUCache:
    def __init__(self, capacity: int, ttl: float, now=time.monotonic):
        ...

    def get(self, key):
        ...

    def put(self, key, value):
        ...

    def __len__(self) -> int:
        ...
```

A bounded cache that evicts by **least-recently-used** order and also **expires**
entries by age.

Behavior:

- `capacity` is the maximum number of live entries. `ttl` is the maximum age, in
  seconds, an entry may live before it is considered expired.
- `get(key)` returns the stored value, or `None` if the key is absent or expired.
  A successful `get` counts as a **use** (it refreshes recency, but **not** the
  entry's age / expiry time).
- `put(key, value)` inserts or updates an entry, marking it most-recently-used and
  **resetting its age** (its timestamp becomes "now"). If inserting a new key
  would exceed `capacity`, evict the least-recently-used live entry first.
- An **expired** entry must never be returned by `get` and must not count toward
  `__len__`. Expired entries may be purged lazily.
- `__len__` returns the number of **live (non-expired)** entries.

## Injectable clock

The constructor takes a `now` callable (defaulting to `time.monotonic`) that
returns the current time as a float. **All time decisions must use `now()`**, not
a hardcoded clock. This lets tests pass a controllable clock for deterministic
behavior. An entry inserted at time `t0` is expired once `now() - t0 >= ttl`
(i.e. an age strictly less than `ttl` is still live).

Example:

```python
clock = [0.0]
cache = LRUCache(capacity=2, ttl=10.0, now=lambda: clock[0])
cache.put("a", 1)
clock[0] = 5.0
assert cache.get("a") == 1     # age 5 < ttl 10 -> live
clock[0] = 10.0
assert cache.get("a") is None  # age 10 >= ttl 10 -> expired
```

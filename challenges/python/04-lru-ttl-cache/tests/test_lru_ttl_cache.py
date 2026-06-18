from solution import LRUCache


def make(capacity=2, ttl=10.0):
    clock = [0.0]
    cache = LRUCache(capacity=capacity, ttl=ttl, now=lambda: clock[0])
    return cache, clock


def test_basic_get_put():
    cache, _ = make()
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("missing") is None


def test_lru_eviction_on_capacity():
    cache, _ = make(capacity=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)  # exceeds capacity -> evict LRU ("a")
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_get_refreshes_recency():
    cache, _ = make(capacity=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1   # "a" now most-recently-used
    cache.put("c", 3)            # should evict "b", not "a"
    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_ttl_expiry_boundary():
    cache, clock = make(ttl=10.0)
    cache.put("a", 1)
    clock[0] = 9.999
    assert cache.get("a") == 1   # age < ttl -> live
    clock[0] = 10.0
    assert cache.get("a") is None  # age == ttl -> expired


def test_get_does_not_reset_age():
    cache, clock = make(ttl=10.0)
    cache.put("a", 1)
    clock[0] = 5.0
    assert cache.get("a") == 1   # use does not refresh age
    clock[0] = 10.0
    assert cache.get("a") is None  # still expires at original t0 + ttl


def test_put_resets_age():
    cache, clock = make(ttl=10.0)
    cache.put("a", 1)
    clock[0] = 8.0
    cache.put("a", 99)           # re-put resets age and value
    clock[0] = 15.0              # 7s after re-put -> still live
    assert cache.get("a") == 99


def test_len_excludes_expired():
    cache, clock = make(capacity=5, ttl=10.0)
    cache.put("a", 1)
    cache.put("b", 2)
    assert len(cache) == 2
    clock[0] = 11.0
    assert len(cache) == 0


def test_expired_entry_does_not_count_against_capacity():
    cache, clock = make(capacity=2, ttl=10.0)
    cache.put("a", 1)
    cache.put("b", 2)
    clock[0] = 11.0              # both expired
    cache.put("c", 3)
    cache.put("d", 4)           # should fit; expired ones purged
    assert cache.get("c") == 3
    assert cache.get("d") == 4
    assert cache.get("a") is None
    assert len(cache) == 2

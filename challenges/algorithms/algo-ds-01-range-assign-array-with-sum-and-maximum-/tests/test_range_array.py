import random
import time

import pytest

from solution import RangeArray


# --------------------------------------------------------------------------
# Brute-force oracle over a plain Python list.
# --------------------------------------------------------------------------

class Brute:
    def __init__(self, data):
        self.a = list(data)

    def assign(self, l, r, v):
        for i in range(l, r):
            self.a[i] = v

    def sum(self, l, r):
        return sum(self.a[l:r])

    def max_subarray(self, l, r):
        return _kadane(self.a[l:r])


def _kadane(vals):
    best = vals[0]
    cur = vals[0]
    for x in vals[1:]:
        cur = max(x, cur + x)
        best = max(best, cur)
    return best


# --------------------------------------------------------------------------
# Basic / worked-example behaviour.
# --------------------------------------------------------------------------

def test_worked_example_sum_and_max_subarray():
    ra = RangeArray([2, -3, 4, -1, 2, 1, -5, 4])
    # Whole array max subarray is [4, -1, 2, 1] = 6.
    assert ra.max_subarray(0, 8) == 6
    assert ra.sum(0, 8) == 4
    # Sub-range [2, 6) = [4, -1, 2, 1] -> best 6, sum 6.
    assert ra.max_subarray(2, 6) == 6
    assert ra.sum(2, 6) == 6


def test_single_element_ranges():
    ra = RangeArray([5, -7, 3])
    assert ra.max_subarray(0, 1) == 5
    assert ra.max_subarray(1, 2) == -7   # forced to take the single element
    assert ra.max_subarray(2, 3) == 3
    assert ra.sum(1, 2) == -7


def test_all_negative_forces_single_best():
    ra = RangeArray([-4, -2, -9, -1, -6])
    # Best non-empty subarray is the single largest element (-1).
    assert ra.max_subarray(0, 5) == -1
    assert ra.max_subarray(0, 3) == -2
    assert ra.sum(0, 5) == -22


def test_assign_updates_both_queries():
    ra = RangeArray([1, 1, 1, 1, 1])
    assert ra.max_subarray(0, 5) == 5
    ra.assign(1, 4, -3)          # -> [1, -3, -3, -3, 1]
    assert ra.sum(0, 5) == -7
    assert ra.max_subarray(0, 5) == 1     # best is a single boundary 1
    ra.assign(0, 5, 2)           # -> all 2s
    assert ra.max_subarray(0, 5) == 10
    assert ra.sum(1, 3) == 4


def test_assign_positive_then_negative_block():
    ra = RangeArray([0] * 6)
    ra.assign(0, 6, 5)           # all 5
    assert ra.max_subarray(0, 6) == 30
    ra.assign(2, 4, -100)        # [5,5,-100,-100,5,5]
    assert ra.max_subarray(0, 6) == 10
    assert ra.max_subarray(0, 2) == 10
    assert ra.max_subarray(4, 6) == 10
    assert ra.max_subarray(2, 4) == -100
    assert ra.sum(0, 6) == -180


def test_zero_assignment():
    ra = RangeArray([-1, -1, -1])
    ra.assign(0, 3, 0)
    assert ra.max_subarray(0, 3) == 0
    assert ra.sum(0, 3) == 0


def test_partial_query_crossing_lazy_boundaries():
    ra = RangeArray(list(range(1, 17)))   # 1..16
    ra.assign(3, 12, -1)   # zero out the middle with -1
    # a = [1,2,3,-1,-1,-1,-1,-1,-1,-1,-1,-1,13,14,15,16]
    assert ra.sum(0, 16) == 1 + 2 + 3 + (-1) * 9 + 13 + 14 + 15 + 16
    assert ra.max_subarray(0, 16) == 13 + 14 + 15 + 16
    # A query window that starts and ends inside assigned/unassigned regions.
    # a[1:13] = [2,3,-1,-1,-1,-1,-1,-1,-1,-1,-1,13]; best is the single 13.
    assert ra.max_subarray(1, 13) == 13
    assert ra.max_subarray(2, 5) == 3           # [3,-1,-1] -> 3


def test_invalid_ranges_raise():
    ra = RangeArray([1, 2, 3])
    for bad in [(-1, 2), (0, 0), (2, 1), (0, 4), (1, 5)]:
        with pytest.raises(IndexError):
            ra.sum(*bad)
        with pytest.raises(IndexError):
            ra.max_subarray(*bad)
    with pytest.raises(IndexError):
        ra.assign(0, 0, 9)
    with pytest.raises(IndexError):
        ra.assign(1, 5, 9)


def test_empty_construction_rejected():
    with pytest.raises(ValueError):
        RangeArray([])


# --------------------------------------------------------------------------
# Randomized correctness against the brute-force oracle.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_random_small_against_brute(seed):
    rng = random.Random(seed)
    n = rng.randint(1, 40)
    data = [rng.randint(-9, 9) for _ in range(n)]
    ra = RangeArray(data)
    br = Brute(data)
    for _ in range(400):
        l = rng.randint(0, n - 1)
        r = rng.randint(l + 1, n)
        op = rng.random()
        if op < 0.4:
            v = rng.randint(-9, 9)
            ra.assign(l, r, v)
            br.assign(l, r, v)
        elif op < 0.7:
            assert ra.sum(l, r) == br.sum(l, r)
        else:
            assert ra.max_subarray(l, r) == br.max_subarray(l, r)


@pytest.mark.parametrize("seed", [10, 11])
def test_random_medium_against_brute(seed):
    rng = random.Random(seed)
    n = rng.randint(200, 500)
    data = [rng.randint(-1000, 1000) for _ in range(n)]
    ra = RangeArray(data)
    br = Brute(data)
    for _ in range(1500):
        l = rng.randint(0, n - 1)
        r = rng.randint(l + 1, n)
        op = rng.random()
        if op < 0.45:
            v = rng.randint(-1000, 1000)
            ra.assign(l, r, v)
            br.assign(l, r, v)
        elif op < 0.7:
            assert ra.sum(l, r) == br.sum(l, r)
        else:
            assert ra.max_subarray(l, r) == br.max_subarray(l, r)


def test_full_range_max_matches_kadane_after_updates():
    rng = random.Random(99)
    n = 300
    data = [rng.randint(-50, 50) for _ in range(n)]
    ra = RangeArray(data)
    mirror = list(data)
    for _ in range(300):
        l = rng.randint(0, n - 1)
        r = rng.randint(l + 1, n)
        v = rng.randint(-50, 50)
        ra.assign(l, r, v)
        mirror[l:r] = [v] * (r - l)
        assert ra.max_subarray(0, n) == _kadane(mirror)
        assert ra.sum(0, n) == sum(mirror)


# --------------------------------------------------------------------------
# Larger / performance-oriented input. A naive O(n) per operation solution
# would time out here; a proper lazy segment tree runs comfortably.
# Correctness is spot-checked on a C-level mirror.
# --------------------------------------------------------------------------

def test_large_performance_and_spot_correctness():
    rng = random.Random(2024)
    n = 20000
    data = [rng.randint(-100, 100) for _ in range(n)]
    ra = RangeArray(data)
    mirror = list(data)   # updated with C-level slice assignment (cheap)

    ops = 40000
    checks = 0
    start = time.time()
    for k in range(ops):
        l = rng.randint(0, n - 1)
        r = rng.randint(l + 1, n)
        roll = rng.random()
        if roll < 0.5:
            v = rng.randint(-100, 100)
            ra.assign(l, r, v)
            mirror[l:r] = [v] * (r - l)
        elif roll < 0.75:
            got = ra.sum(l, r)
            if k % 200 == 0:          # spot check (O(n) each, sampled)
                assert got == sum(mirror[l:r])
                checks += 1
        else:
            got = ra.max_subarray(l, r)
            if k % 200 == 0:
                assert got == _kadane(mirror[l:r])
                checks += 1
    elapsed = time.time() - start
    assert checks > 0
    # Generous ceiling: the reference finishes well under this.
    assert elapsed < 25.0

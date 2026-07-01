import random
import time

import pytest

from solution import count_harshad


# ---------------------------------------------------------------------------
# Independent, obviously-correct oracle (feasible only for small bounds).
# ---------------------------------------------------------------------------
def _digit_sum(x: int) -> int:
    s = 0
    while x:
        s += x % 10
        x //= 10
    return s


def _is_harshad(x: int) -> bool:
    if x <= 0:
        return False
    ds = _digit_sum(x)
    return x % ds == 0


def _brute(L: int, R: int) -> int:
    return sum(1 for x in range(L, R + 1) if _is_harshad(x))


# ---------------------------------------------------------------------------
# Tiny hand-checked cases.
# ---------------------------------------------------------------------------
def test_single_digits_all_harshad():
    # 1..9 are each divisible by themselves.
    assert count_harshad(1, 9) == 9


def test_ten_is_harshad():
    # digit sum 1, 10 % 1 == 0
    assert count_harshad(10, 10) == 1


def test_eleven_is_not_harshad():
    # digit sum 2, 11 % 2 == 1
    assert count_harshad(11, 11) == 0


def test_known_small_range():
    # Harshad in [1,20]: 1..9, 10, 12, 18, 20  -> 13
    assert count_harshad(1, 20) == 13


def test_specific_membership():
    for x in (12, 18, 20, 21, 24, 27, 100, 102):
        assert count_harshad(x, x) == 1, x
    for x in (11, 13, 14, 19, 23, 101):
        assert count_harshad(x, x) == 0, x


# ---------------------------------------------------------------------------
# Boundary / edge cases.
# ---------------------------------------------------------------------------
def test_zero_never_counted():
    # 0 has digit sum 0 -> not a Harshad number, division undefined.
    assert count_harshad(0, 0) == 0


def test_range_starting_at_zero_matches_starting_at_one():
    assert count_harshad(0, 500) == count_harshad(1, 500)


def test_empty_when_L_equals_R_non_harshad():
    assert count_harshad(13, 13) == 0


def test_L_equals_R_harshad():
    assert count_harshad(24, 24) == 1


def test_inclusive_both_endpoints():
    # 20 and 21 are both Harshad; range should include both ends.
    assert count_harshad(20, 21) == 2


def test_full_prefix_equals_oracle_small():
    for N in (1, 2, 5, 9, 10, 20, 50, 99, 100, 200, 999, 1000):
        assert count_harshad(1, N) == _brute(1, N), N


# ---------------------------------------------------------------------------
# Randomised cross-checks against the brute-force oracle.
# ---------------------------------------------------------------------------
def test_random_ranges_small():
    rng = random.Random(20260701)
    for _ in range(60):
        a = rng.randint(0, 5000)
        b = rng.randint(0, 5000)
        lo, hi = min(a, b), max(a, b)
        assert count_harshad(lo, hi) == _brute(lo, hi), (lo, hi)


def test_random_ranges_larger():
    rng = random.Random(777)
    for _ in range(8):
        a = rng.randint(0, 200_000)
        b = rng.randint(0, 200_000)
        lo, hi = min(a, b), max(a, b)
        assert count_harshad(lo, hi) == _brute(lo, hi), (lo, hi)


def test_prefix_up_to_one_million():
    # A genuinely larger exact check the oracle can still handle.
    assert count_harshad(1, 1_000_000) == _brute(1, 1_000_000)


# ---------------------------------------------------------------------------
# Additivity / consistency (works for bounds far beyond brute force).
# ---------------------------------------------------------------------------
def test_additivity_over_split_points():
    rng = random.Random(42)
    for _ in range(15):
        lo = rng.randint(0, 10_000)
        mid = rng.randint(lo, lo + 20_000)
        hi = rng.randint(mid, mid + 20_000)
        total = count_harshad(lo, hi)
        parts = count_harshad(lo, mid) + count_harshad(mid + 1, hi)
        assert total == parts, (lo, mid, hi)


def test_large_bounds_additive_consistency():
    # Bounds well past what brute force can enumerate; we only assert internal
    # consistency (and that the DP terminates quickly).
    splits = [
        (1, 123_456_789, 999_999_999),
        (10_000_000, 543_210_000, 1_000_000_000),
    ]
    for lo, mid, hi in splits:
        assert count_harshad(lo, hi) == count_harshad(lo, mid) + count_harshad(mid + 1, hi)


def test_large_bound_completes_in_time():
    start = time.time()
    val = count_harshad(1, 1_000_000_000)
    elapsed = time.time() - start
    assert val > 0
    # Must be an efficient digit DP, not enumeration.
    assert elapsed < 20.0, f"too slow: {elapsed:.1f}s"

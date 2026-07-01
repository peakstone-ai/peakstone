from functools import lru_cache


def _count_upto(N: int, s: int) -> int:
    """Count integers x with 0 <= x <= N such that
    (sum of decimal digits of x) == s   AND   x % s == 0.

    `s` is guaranteed >= 1 by the caller, so x == 0 (digit sum 0) is
    never counted here.
    """
    if N < 0:
        return 0
    digits = [int(c) for c in str(N)]
    n = len(digits)

    @lru_cache(maxsize=None)
    def dp(pos: int, tight: bool, dsum: int, rem: int) -> int:
        # Prune: digit sum can only grow, so overshooting the target is dead.
        if dsum > s:
            return 0
        if pos == n:
            return 1 if (dsum == s and rem == 0) else 0
        limit = digits[pos] if tight else 9
        total = 0
        for d in range(0, limit + 1):
            total += dp(pos + 1, tight and (d == limit), dsum + d, (rem * 10 + d) % s)
        return total

    result = dp(0, True, 0, 0)
    dp.cache_clear()
    return result


def _count_to(N: int) -> int:
    """Number of Harshad numbers in [1, N]."""
    if N < 1:
        return 0
    max_digit_sum = 9 * len(str(N))
    return sum(_count_upto(N, s) for s in range(1, max_digit_sum + 1))


def count_harshad(L: int, R: int) -> int:
    """Return the number of integers x with L <= x <= R that are divisible by
    the sum of their own decimal digits (Harshad / Niven numbers).

    0 <= L <= R. The integer 0 is never counted (its digit sum is 0).
    """
    return _count_to(R) - _count_to(L - 1)

import random

import pytest

from solution import discrete_log


def brute(a, b, m, cap):
    """Smallest x in [0, cap) with a**x == b (mod m), else -1."""
    a %= m
    b %= m
    cur = 1 % m
    for x in range(cap):
        if cur == b:
            return x
        cur = (cur * a) % m
    return -1


# ---------------------------------------------------------------- basic anchors
def test_zero_exponent_when_b_is_one():
    assert discrete_log(2, 1, 10) == 0
    assert discrete_log(3, 1, 100) == 0
    # any base with b == 1 mod m -> x = 0
    assert discrete_log(5, 1, 7) == 0


def test_simple_coprime():
    assert discrete_log(2, 8, 10) == 3        # 2^3 = 8
    assert discrete_log(3, 13, 17) == 4       # 3^4 = 81 = 13 (mod 17)
    assert discrete_log(5, 3, 23) == 16


def test_no_solution_small():
    assert discrete_log(2, 3, 10) == -1       # {1,2,4,8,6} never hits 3
    assert discrete_log(4, 7, 13) == -1       # subgroup {1,4,3,12,9,10}
    assert discrete_log(6, 8, 10) == -1


# ------------------------------------------------ non-coprime base and modulus
def test_non_coprime_reachable_in_cycle():
    # powers of 2 mod 10: 1,2,4,8,6,2,4,8,6,...  -> first 6 at x = 4
    assert discrete_log(2, 6, 10) == 4
    # powers of 10 mod 100: 1,10,0,0,...
    assert discrete_log(10, 10, 100) == 1
    assert discrete_log(10, 0, 100) == 2
    assert discrete_log(10, 50, 100) == -1


def test_reaches_zero_tail():
    assert discrete_log(2, 0, 1024) == 10     # 2^10 = 1024 = 0 (mod 1024)
    assert discrete_log(6, 0, 8) == 3         # 6^1=6,6^2=36=4,6^3=216=0


# ----------------------------------------------------------- degenerate inputs
def test_modulus_one():
    # everything is congruent to 0 mod 1, so x = 0 always
    for a in range(0, 5):
        for b in range(0, 5):
            assert discrete_log(a, b, 1) == 0


def test_base_zero():
    # 0^0 = 1, 0^k = 0 for k >= 1
    assert discrete_log(0, 1, 7) == 0
    assert discrete_log(0, 0, 7) == 1
    assert discrete_log(0, 3, 7) == -1


def test_inputs_reduced_mod_m():
    # a, b larger than m must be reduced first
    assert discrete_log(12, 18, 10) == discrete_log(2, 8, 10) == 3
    assert discrete_log(2 + 10 ** 6, 8, 10) == 3


# --------------------------------------------- exhaustive minimality guarantee
def test_exhaustive_matches_brute_force():
    fails = []
    for m in range(1, 70):
        cap = m + 5  # covers the whole pre-period + period
        for a in range(m):
            for b in range(m):
                got = discrete_log(a, b, m)
                exp = brute(a, b, m, cap)
                if got != exp:
                    fails.append((a, b, m, got, exp))
    assert not fails, fails[:10]


# --------------------------------------------------- large solvable (property)
def test_large_solvable_validity_and_minimal_bound():
    rng = random.Random(12345)
    for _ in range(300):
        m = rng.randint(2, 10 ** 9)
        a = rng.randint(0, m - 1)
        x = rng.randint(0, 2 * 10 ** 6)
        b = pow(a, x, m)
        r = discrete_log(a, b, m)
        assert r != -1
        assert pow(a, r, m) == b
        assert 0 <= r <= x            # returned x must be the *smallest*


def test_large_forces_subquadratic_prime():
    # ~1e12 prime; an O(m) scan would blow the time limit, an O(sqrt m) one won't
    m = 999999999989
    a = 7
    x = 654321
    b = pow(a, x, m)
    r = discrete_log(a, b, m)
    assert pow(a, r, m) == b
    assert 0 <= r <= x


def test_large_no_solution_full_cycle():
    # p prime; a is a quadratic residue (its subgroup = the QRs), b a non-residue,
    # so b is unreachable. A brute-force scan would traverse the whole (huge)
    # cycle before giving up -> must be handled by the fast algorithm.
    p = 1000000007
    a = pow(3, 2, p)          # a quadratic residue
    b = 5                     # verified quadratic non-residue below
    assert pow(b, (p - 1) // 2, p) == p - 1
    assert discrete_log(a, b, p) == -1


def test_large_no_solution_composite():
    # under an even modulus, powers of 4 (or 2) can never equal an odd target
    m = 2 ** 20
    assert discrete_log(4, 3, m) == -1        # powers of 4 are 1 or even
    assert discrete_log(2, 3, m) == -1        # powers of 2: 1,2,4,...,0 never 3

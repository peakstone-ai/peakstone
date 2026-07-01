import math


def _bsgs(a, b, m):
    """Smallest y >= 0 with a**y == b (mod m), assuming gcd(a, m) == 1.

    Returns -1 if no such y exists.
    """
    a %= m
    b %= m
    if m == 1:
        return 0
    n = math.isqrt(m) + 1
    # Baby steps: map a**j -> smallest j, for j in [0, n).
    table = {}
    e = 1 % m
    for j in range(n):
        if e not in table:
            table[e] = j
        e = (e * a) % m
    an = e  # a**n
    ainv_n = pow(an, -1, m)  # (a**n)**-1, valid because gcd(a, m) == 1
    # Giant steps: look for b * (a**-n)**i in the table; ascending i => minimal y.
    giant = b
    for i in range(n + 1):
        if giant in table:
            return i * n + table[giant]
        giant = (giant * ainv_n) % m
    return -1


def discrete_log(a: int, b: int, m: int) -> int:
    """Smallest x >= 0 with a**x == b (mod m), or -1 if none exists.

    Works for an arbitrary modulus m >= 1, including the case gcd(a, m) > 1.
    """
    if m <= 0:
        raise ValueError("m must be positive")
    if m == 1:
        return 0
    a %= m
    b %= m
    # Reduction phase: peel off common factors of gcd(a, m) one exponent at a
    # time. At the start of each iteration k == a**add (mod current m); checking
    # b == k tests x == add, so the first hit gives the minimal tail solution.
    k = 1 % m
    add = 0
    while True:
        g = math.gcd(a, m)
        if g == 1:
            break
        if b == k:
            return add
        if b % g:
            return -1
        b //= g
        m //= g
        add += 1
        k = (k * (a // g)) % m
        a %= m
    if m == 1:
        # After reduction everything is congruent mod 1; x == add works.
        return add
    # Now gcd(a, m) == 1. Solve a**y * k == b (mod m); answer = add + y.
    kinv = pow(k, -1, m)
    target = (b * kinv) % m
    y = _bsgs(a, target, m)
    if y == -1:
        return -1
    return add + y

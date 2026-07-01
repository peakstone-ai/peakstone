# Generalized discrete logarithm

Implement a file **`solution.py`** containing a function `discrete_log` that
solves the **discrete logarithm** problem for an **arbitrary** modulus:

```python
def discrete_log(a: int, b: int, m: int) -> int:
    """Return the smallest non-negative integer x such that

        a**x is congruent to b (mod m)

    or -1 if no such x exists."""
```

## Inputs

- `a`, `b` are integers with `a >= 0` and `b >= 0`. They may be larger than `m`;
  reduce them modulo `m` before doing anything.
- `m` is the modulus with `m >= 1`.

## What you must return

The **smallest** integer `x >= 0` with `a**x ≡ b (mod m)`, using the convention
`a**0 == 1`. If no such `x` exists, return `-1`.

Because you must return the *smallest* solution, ties are impossible: the answer
is unique.

## The catch: `m` need not be prime, and `a` need not be coprime to `m`

This is the whole difficulty of the problem.

- When `gcd(a, m) == 1`, the powers `a**0, a**1, a**2, ...` cycle through a group
  and the classic **baby-step giant-step** meet-in-the-middle idea applies.
- When `gcd(a, m) > 1`, the sequence of powers is **not** a clean cycle — it has a
  "tail" (a pre-period) before it becomes periodic, and `a` is never invertible
  modulo `m`. A solution may lie in the tail (small `x`) **or** deep inside the
  periodic part (large `x`), and it may not exist at all. You must handle every
  combination correctly, still returning the *smallest* `x`.

## Efficiency

A naive `O(m)` scan over exponents will **not** pass: some tests use a modulus of
size roughly `10**12` and cases with no solution, where scanning the whole cycle
would exceed the time limit. You are expected to use a sub-linear
(≈ `O(sqrt(m))`) approach such as an extended baby-step giant-step that first
factors out `gcd(a, m)`.

## Examples

```python
assert discrete_log(2, 8, 10) == 3     # 2**3 = 8
assert discrete_log(2, 1, 10) == 0     # 2**0 = 1
assert discrete_log(2, 6, 10) == 4     # powers of 2 mod 10: 1,2,4,8,6,... -> 6 at x=4
assert discrete_log(2, 3, 10) == -1    # 3 is never a power of 2 mod 10
assert discrete_log(3, 13, 17) == 4    # 3**4 = 81 = 13 (mod 17)
assert discrete_log(2, 0, 1024) == 10  # 2**10 = 1024 = 0 (mod 1024)
assert discrete_log(0, 0, 7) == 1      # 0**0 = 1, 0**1 = 0
assert discrete_log(0, 1, 7) == 0      # 0**0 = 1
assert discrete_log(5, 3, 5) == 0 or True  # (illustrative)
```

## Edge cases to respect

- `m == 1`: every integer is `≡ 0 (mod 1)`, so the answer is always `0`.
- `b ≡ 1 (mod m)`: the answer is `0` (since `a**0 == 1`), for any `a`.
- `a ≡ 0 (mod m)`: `0**0 == 1`, and `0**k == 0` for `k >= 1`.
- Inputs `a`, `b` may exceed `m` and must be reduced modulo `m` first.

You may use `math.gcd`, `math.isqrt`, and Python's built-in modular inverse
`pow(x, -1, m)`. Do not import any discrete-log or number-theory library that
solves the problem for you.
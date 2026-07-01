# Counting Harshad numbers in a range

Implement a file **`solution.py`** containing a function `count_harshad` that
counts how many integers in a closed range are **Harshad numbers**.

```python
def count_harshad(L: int, R: int) -> int:
    """Return the number of integers x with L <= x <= R that are divisible by
    the sum of their own decimal digits."""
```

## Definitions

For a positive integer `x`, let `digitsum(x)` be the sum of its decimal digits
(e.g. `digitsum(132) = 1 + 3 + 2 = 6`).

`x` is a **Harshad number** (also called a *Niven number*) iff `x > 0` and

```
x % digitsum(x) == 0
```

i.e. `x` is divisible by the sum of its own digits. For example:

- `18` is Harshad: `digitsum(18) = 9`, and `18 % 9 == 0`.
- `11` is **not** Harshad: `digitsum(11) = 2`, and `11 % 2 == 1`.
- Every one-digit number `1..9` is Harshad (each divides itself).

The integer `0` is **never** a Harshad number: its digit sum is `0` and division
by zero is undefined, so it must **not** be counted.

## Task

Given `L` and `R` with `0 <= L <= R`, return the count of Harshad numbers `x`
satisfying `L <= x <= R`. **Both endpoints are inclusive.**

## Constraints

- `0 <= L <= R <= 10**18`.

The upper bound is far too large to enumerate the range one integer at a time —
counting `10**18` numbers individually is hopeless. Your solution must be able to
answer queries near the maximum bound **quickly** (well under a second for a
single call in the worst case). This forces a counting approach rather than
brute-force iteration.

## Examples

```python
assert count_harshad(1, 9) == 9        # all single digits
assert count_harshad(10, 10) == 1      # digitsum 1 divides everything
assert count_harshad(11, 11) == 0      # 11 % 2 != 0
assert count_harshad(1, 20) == 13      # 1..9, 10, 12, 18, 20
assert count_harshad(0, 0) == 0        # 0 is never Harshad
assert count_harshad(1, 100) == 33
assert count_harshad(1, 1000) == 213
assert count_harshad(100, 200) == 27
```

## Notes

- The range is inclusive on both ends.
- A range that begins at `0` gives the same answer as one beginning at `1`
  (since `0` is never counted): `count_harshad(0, R) == count_harshad(1, R)`.
- You may assume the inputs are non-negative integers with `L <= R`.

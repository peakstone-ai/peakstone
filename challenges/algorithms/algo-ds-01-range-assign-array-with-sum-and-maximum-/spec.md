# Range-assign array with sum and maximum-subarray queries

Implement a file **`solution.py`** containing a class `RangeArray` that maintains an
array of integers under **range-assignment** updates while answering two kinds of
range queries efficiently: the **sum** of a range, and the **maximum-subarray sum**
within a range.

```python
class RangeArray:
    def __init__(self, data):
        """Build the structure from an iterable of ints. `len(data) >= 1`."""

    def assign(self, l, r, v):
        """Set a[i] = v for every index i with l <= i < r."""

    def sum(self, l, r):
        """Return the sum of a[l:r]."""

    def max_subarray(self, l, r):
        """Return the maximum sum over all NON-EMPTY contiguous subarrays that lie
        entirely within a[l:r]."""
```

## Indexing and ranges

- Indices are **0-based**.
- Every range `[l, r)` is **half-open**: it covers indices `l, l+1, ..., r-1`.
- All three methods require a **valid, non-empty** range: `0 <= l < r <= n`, where
  `n` is the length of the array. If the range is invalid (out of bounds, or `l >= r`),
  the method must raise **`IndexError`**.
- Constructing a `RangeArray` from an **empty** iterable must raise **`ValueError`**.

## Semantics

- **`assign(l, r, v)`** overwrites every element in `[l, r)` with the integer `v`.
  Elements outside the range are untouched. Values (both stored and assigned) may be
  **negative, zero, or positive**, and may be large.
- **`sum(l, r)`** returns `a[l] + a[l+1] + ... + a[r-1]` reflecting **all** updates
  applied so far.
- **`max_subarray(l, r)`** returns the largest possible value of
  `a[i] + a[i+1] + ... + a[j]` over all `l <= i <= j < r`. The subarray must be
  **non-empty**, so it always contains at least one element. Consequently, when every
  element in the range is negative the answer is the single **largest** (least
  negative) element — the empty subarray is **not** allowed.

The number of operations can be large, so both queries and updates must be
**sub-linear per call** in the array length (a lazy segment tree is the intended
approach). A solution that scans the affected range on every operation will be too
slow on the larger tests.

## Worked example

```python
ra = RangeArray([2, -3, 4, -1, 2, 1, -5, 4])
assert ra.max_subarray(0, 8) == 6   # [4, -1, 2, 1]
assert ra.sum(0, 8) == 4
assert ra.max_subarray(2, 6) == 6   # [4, -1, 2, 1] within a[2:6]

ra.assign(2, 4, -100)               # a = [2, -3, -100, -100, 2, 1, -5, 4]
assert ra.sum(0, 8) == -199
assert ra.max_subarray(0, 8) == 4   # the trailing single 4
assert ra.max_subarray(4, 6) == 3   # [2, 1]

ra.assign(0, 8, 5)                  # all fives
assert ra.max_subarray(0, 8) == 40
assert ra.sum(3, 7) == 20

neg = RangeArray([-4, -2, -9, -1, -6])
assert neg.max_subarray(0, 5) == -1  # best non-empty subarray is a single element
```

# Longest k-repeated substring

Implement a file **`solution.py`** containing a function `longest_k_repeated`:

```python
def longest_k_repeated(s: str, k: int) -> int:
    """Return the length of the longest substring of `s` that occurs
    at least `k` times."""
```

Given a string `s` and an integer `k >= 1`, return the **length of the longest
non-empty substring** of `s` that occurs **at least `k` times** in `s`. If no
non-empty substring occurs at least `k` times, return `0`.

## What counts as an occurrence

- An occurrence is a **distinct starting position** in `s`. A substring of
  length `L` occurs at position `i` iff `s[i:i+L]` equals it.
- **Overlaps are allowed.** For example, in `"aaaa"` the substring `"aaa"`
  occurs at positions `0` and `1`, so it occurs **2** times.
- The string is compared **exactly**, character by character; matching is
  **case-sensitive** and works over arbitrary Unicode characters.

## Precise definition

Return the largest `L >= 1` such that there exists a string `w` of length `L`
for which the number of indices `i` with `s[i:i+L] == w` is `>= k`. If no such
`L` exists, return `0`.

## Edge cases

- `k == 1`: every non-empty substring occurs at least once, so for a non-empty
  `s` the answer is `len(s)` (the whole string occurs once). For the empty
  string the answer is `0`.
- The empty string returns `0` for **every** `k`.
- If `k` exceeds the length of the longest single-character run and the string
  has no repeats at all (e.g. all-distinct characters), smaller substrings may
  still fail the threshold — return `0` when nothing qualifies.

## Worked examples

```python
assert longest_k_repeated("banana", 2) == 3    # "ana" occurs at 1 and 3 (overlap)
assert longest_k_repeated("banana", 3) == 1    # only single chars occur >= 3 times
assert longest_k_repeated("banana", 4) == 0
assert longest_k_repeated("aaa", 2) == 2       # "aa" at 0 and 1
assert longest_k_repeated("aaa", 3) == 1       # "a" x3
assert longest_k_repeated("abcabc", 1) == 6    # whole string, k==1
assert longest_k_repeated("abcdef", 2) == 0    # all distinct, nothing repeats
assert longest_k_repeated("", 5) == 0
```

## Efficiency

Inputs can be **large**: `len(s)` up to about `100000`. A naive approach that
enumerates every substring is `O(n^2)` in time and memory and will time out.
Aim for roughly `O(n)` or `O(n log n)`. (A suffix automaton, or a suffix array
with LCP, or binary-search-plus-hashing all work.)

## Constraints

- `1 <= k`
- `0 <= len(s) <= 100000`
- `s` consists of arbitrary characters (tests use printable ASCII).
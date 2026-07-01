# Freelance gig scheduling for maximum payout

You are a freelancer planning your calendar. There is a queue of one-day gigs
on offer. Each gig `i` has:

- a **deadline** `d_i` (a positive integer) — the gig is only worth anything if
  you complete it on or before day `d_i`, and
- a **payout** `p_i` (a non-negative integer) — what you earn if you complete it
  in time.

Days are numbered `1, 2, 3, ...`. Every gig takes **exactly one full day**, and
you can work on **at most one gig per day**. You may accept any subset of the
gigs and choose which day to do each accepted gig, as long as no two accepted
gigs share a day and each accepted gig is done on some day `<= its deadline`.
Gigs you don't accept earn nothing.

Implement a file **`solution.py`** containing:

```python
def max_payout(gigs: list[tuple[int, int]]) -> int:
    """Return the maximum total payout achievable.

    `gigs` is a list of (deadline, payout) pairs. Return an int.
    """
```

## What to return

Return the **maximum total payout** you can earn with a valid schedule. You do
**not** need to return the schedule itself — only the best achievable total.

## Why this is subtle

A tempting greedy — "sort gigs by payout, and place each accepted gig on the
earliest free day within its deadline" — is **wrong**. Consider two gigs:

- gig A: deadline 2, payout 100
- gig B: deadline 1, payout 50

The correct answer is **150**: do A on day 2 and B on day 1. But if you place
the higher-payout gig A on the *earliest* free day (day 1), you occupy the only
day B could ever use, and you're stuck with just 100. The fix is an
exchange-argument insight: when you accept a gig, reserve it as **late** as its
deadline allows, keeping earlier days open for gigs with tighter deadlines.
Likewise, sorting purely by deadline (or accepting gigs first-come) can force
you to keep a cheap gig over a strictly better one competing for the same day.

## Constraints

- `0 <= len(gigs)`; large instances (up to `2 * 10^5` gigs) are tested, so an
  `O(n^2)` day-by-day scan will be too slow — aim for roughly `O(n log n)`.
- `1 <= d_i` and `0 <= p_i`, each up to about `10^9`. Deadlines may be far
  larger than the number of gigs.
- The empty gig list returns `0`.

## Examples

```python
assert max_payout([]) == 0
assert max_payout([(1, 42)]) == 42
assert max_payout([(2, 100), (1, 50)]) == 150          # place the rich gig late
assert max_payout([(1, 1), (1, 100)]) == 100           # one day-1 slot, keep 100
assert max_payout([(2, 100), (1, 19), (2, 27), (1, 25), (3, 15)]) == 142
assert max_payout([(1000, 5), (1000, 6), (1000, 7)]) == 18  # all fit
```

import heapq
import itertools
import random

from solution import max_payout


# ----------------------------------------------------------------------------
# Independent oracles used to check the solution on random / large inputs.
# ----------------------------------------------------------------------------

def heap_oracle(gigs):
    """Classic min-heap greedy for job sequencing with deadlines.

    Process gigs in increasing deadline order, keep a min-heap of accepted
    payouts, and whenever more gigs are accepted than the current deadline
    allows, drop the smallest-payout accepted gig. The heap's sum is optimal.
    This is a different implementation from the reference (which uses a
    disjoint-set over day-slots), so agreement is a strong correctness signal.
    """
    heap = []
    for d, p in sorted(gigs, key=lambda x: x[0]):
        heapq.heappush(heap, p)
        if len(heap) > d:
            heapq.heappop(heap)
    return sum(heap)


def brute_force(gigs):
    """Exhaustive optimum for tiny inputs.

    Try every subset of gigs; a subset is schedulable iff we can match each
    gig to a distinct day <= its deadline (checked by the standard earliest
    -deadline-first feasibility greedy). Only feasible for very small n.
    """
    n = len(gigs)
    best = 0
    for r in range(n + 1):
        for subset in itertools.combinations(range(n), r):
            chosen = sorted(subset, key=lambda i: gigs[i][0])
            day = 0
            ok = True
            for i in chosen:
                day += 1
                if day > gigs[i][0]:
                    ok = False
                    break
            if ok:
                best = max(best, sum(gigs[i][1] for i in subset))
    return best


# ----------------------------------------------------------------------------
# Hand-verified small cases.
# ----------------------------------------------------------------------------

def test_empty():
    assert max_payout([]) == 0


def test_single_gig_within_deadline():
    assert max_payout([(1, 42)]) == 42
    assert max_payout([(5, 7)]) == 7


def test_two_gigs_no_conflict():
    assert max_payout([(1, 10), (2, 20)]) == 30


def test_latest_slot_subtlety():
    # The exchange-argument crux: the high-payout gig has the LATER deadline.
    # Placing it at its latest feasible day (day 2) leaves day 1 free for the
    # tight-deadline gig, yielding 150. A greedy that places the high-payout
    # gig at the EARLIEST free day (day 1) blocks the other gig -> only 100.
    assert max_payout([(2, 100), (1, 50)]) == 150


def test_must_prefer_higher_payout_on_tie_deadline():
    assert max_payout([(1, 1), (1, 100)]) == 100
    assert max_payout([(1, 100), (1, 1)]) == 100


def test_classic_five_gig_instance():
    gigs = [(2, 100), (1, 19), (2, 27), (1, 25), (3, 15)]
    assert max_payout(gigs) == 142


def test_four_gig_instance():
    assert max_payout([(1, 10), (2, 10), (2, 15), (1, 20)]) == 35


def test_all_same_deadline_one():
    assert max_payout([(1, 3), (1, 9), (1, 4), (1, 2)]) == 9


def test_deadlines_far_beyond_count():
    assert max_payout([(1000, 5), (1000, 6), (1000, 7)]) == 18


def test_greedy_by_deadline_alone_is_wrong():
    gigs = [(1, 5), (2, 6), (2, 7), (3, 4), (1, 20), (3, 3)]
    assert max_payout(gigs) == brute_force(gigs)


def test_zero_payout_gigs_are_never_harmful():
    assert max_payout([(1, 0), (1, 0)]) == 0
    assert max_payout([(2, 0), (1, 5)]) == 5


# ----------------------------------------------------------------------------
# Randomized cross-checks against brute force (small) and heap oracle.
# ----------------------------------------------------------------------------

def test_random_small_vs_bruteforce():
    rng = random.Random(1234)
    for _ in range(400):
        n = rng.randint(0, 7)
        gigs = [(rng.randint(1, 6), rng.randint(0, 50)) for _ in range(n)]
        assert max_payout(gigs) == brute_force(gigs)


def test_random_medium_vs_heap_oracle():
    rng = random.Random(99)
    for _ in range(60):
        n = rng.randint(1, 500)
        gigs = [(rng.randint(1, n + 5), rng.randint(1, 10**6)) for _ in range(n)]
        assert max_payout(gigs) == heap_oracle(gigs)


def test_random_tight_deadlines_vs_heap_oracle():
    rng = random.Random(7)
    for _ in range(60):
        n = rng.randint(1, 400)
        maxd = rng.randint(1, 5)
        gigs = [(rng.randint(1, maxd), rng.randint(1, 1000)) for _ in range(n)]
        assert max_payout(gigs) == heap_oracle(gigs)


def test_large_input_performance_and_correctness():
    # Big instance: an O(n^2) slot scan would blow the time budget, and a
    # naive greedy would give a wrong total. Must match the heap oracle.
    rng = random.Random(2024)
    n = 200_000
    gigs = [(rng.randint(1, 10**9), rng.randint(1, 10**9)) for _ in range(n)]
    assert max_payout(gigs) == heap_oracle(gigs)


def test_large_tight_deadlines():
    rng = random.Random(555)
    n = 200_000
    gigs = [(rng.randint(1, 50), rng.randint(1, 10**9)) for _ in range(n)]
    assert max_payout(gigs) == heap_oracle(gigs)

def max_payout(gigs):
    """Maximum total payout for unit-time deadline-constrained gigs.

    `gigs` is a list of (deadline, payout) pairs with deadline >= 1 and
    payout >= 0 (both integers). Each gig takes exactly one day; at most one
    gig can be worked per day (days are 1, 2, 3, ...). A gig earns its payout
    only if it is scheduled on some day <= its deadline. Return the maximum
    achievable total payout.
    """
    if not gigs:
        return 0

    n = len(gigs)
    # A schedule uses at most n days, so any deadline beyond n is equivalent
    # to a deadline of n (there is never a reason to use day > n).
    jobs = sorted(((p, d if d < n else n) for d, p in gigs), reverse=True)

    # Disjoint-set over day-slots 0..n. find(x) returns the greatest free
    # day <= x, or 0 if none is free. Slot 0 is the sentinel "no free day".
    parent = list(range(n + 1))

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    total = 0
    for p, d in jobs:
        slot = find(d)
        if slot > 0:
            total += p
            parent[slot] = slot - 1  # consume this day; point to the next lower
    return total

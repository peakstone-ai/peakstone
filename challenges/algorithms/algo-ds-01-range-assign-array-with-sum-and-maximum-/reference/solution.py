import sys


class RangeArray:
    """A segment tree over an integer array supporting range-assignment
    updates and both range-sum and range maximum-subarray queries.

    Indices are 0-based and all ranges are half-open: [l, r) covers the
    indices l, l+1, ..., r-1.
    """

    __slots__ = ("n", "total", "pre", "suf", "best", "tag")

    def __init__(self, data):
        data = list(data)
        n = len(data)
        if n == 0:
            raise ValueError("RangeArray requires at least one element")
        self.n = n
        size = 4 * n
        self.total = [0] * size
        self.pre = [0] * size
        self.suf = [0] * size
        self.best = [0] * size
        self.tag = [None] * size
        sys.setrecursionlimit(max(1000, 4 * n))
        self._build(1, 0, n, data)

    # ---- internal helpers ------------------------------------------------

    def _set_leaf(self, node, v):
        self.total[node] = v
        self.pre[node] = v
        self.suf[node] = v
        self.best[node] = v

    def _apply_assign(self, node, lo, hi, v):
        length = hi - lo
        self.total[node] = v * length
        if v >= 0:
            best = v * length
        else:
            best = v
        self.pre[node] = best
        self.suf[node] = best
        self.best[node] = best
        self.tag[node] = v

    def _pull(self, node):
        l = 2 * node
        r = 2 * node + 1
        tl, tr = self.total[l], self.total[r]
        self.total[node] = tl + tr
        self.pre[node] = max(self.pre[l], tl + self.pre[r])
        self.suf[node] = max(self.suf[r], tr + self.suf[l])
        self.best[node] = max(self.best[l], self.best[r], self.suf[l] + self.pre[r])

    def _push_down(self, node, lo, hi):
        t = self.tag[node]
        if t is not None:
            mid = (lo + hi) // 2
            self._apply_assign(2 * node, lo, mid, t)
            self._apply_assign(2 * node + 1, mid, hi, t)
            self.tag[node] = None

    def _build(self, node, lo, hi, data):
        if hi - lo == 1:
            self._set_leaf(node, data[lo])
            return
        mid = (lo + hi) // 2
        self._build(2 * node, lo, mid, data)
        self._build(2 * node + 1, mid, hi, data)
        self._pull(node)

    def _update(self, node, lo, hi, ql, qr, v):
        if qr <= lo or hi <= ql:
            return
        if ql <= lo and hi <= qr:
            self._apply_assign(node, lo, hi, v)
            return
        self._push_down(node, lo, hi)
        mid = (lo + hi) // 2
        self._update(2 * node, lo, mid, ql, qr, v)
        self._update(2 * node + 1, mid, hi, ql, qr, v)
        self._pull(node)

    def _query(self, node, lo, hi, ql, qr):
        # returns a tuple (total, pre, suf, best) for the part of this node
        # inside [ql, qr), or None if disjoint.
        if qr <= lo or hi <= ql:
            return None
        if ql <= lo and hi <= qr:
            return (self.total[node], self.pre[node], self.suf[node], self.best[node])
        self._push_down(node, lo, hi)
        mid = (lo + hi) // 2
        left = self._query(2 * node, lo, mid, ql, qr)
        right = self._query(2 * node + 1, mid, hi, ql, qr)
        if left is None:
            return right
        if right is None:
            return left
        lt, lp, ls, lb = left
        rt, rp, rs, rb = right
        total = lt + rt
        pre = max(lp, lt + rp)
        suf = max(rs, rt + ls)
        best = max(lb, rb, ls + rp)
        return (total, pre, suf, best)

    # ---- public API ------------------------------------------------------

    def assign(self, l, r, v):
        """Set a[i] = v for every i with l <= i < r."""
        if not (0 <= l < r <= self.n):
            raise IndexError("invalid range")
        self._update(1, 0, self.n, l, r, v)

    def sum(self, l, r):
        """Return the sum of a[l:r]."""
        if not (0 <= l < r <= self.n):
            raise IndexError("invalid range")
        res = self._query(1, 0, self.n, l, r)
        return res[0]

    def max_subarray(self, l, r):
        """Return the maximum sum over all non-empty contiguous subarrays
        that lie entirely within a[l:r]."""
        if not (0 <= l < r <= self.n):
            raise IndexError("invalid range")
        res = self._query(1, 0, self.n, l, r)
        return res[3]

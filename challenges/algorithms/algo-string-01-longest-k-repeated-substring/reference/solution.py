def longest_k_repeated(s: str, k: int) -> int:
    """Length of the longest substring of `s` occurring at least `k` times.

    Occurrences are counted by distinct starting positions; overlaps are
    allowed. Returns 0 when no non-empty substring occurs at least k times.
    """
    n = len(s)
    if n == 0 or k < 1:
        return 0
    if k == 1:
        return n

    # Suffix automaton.
    nxt = [dict()]
    link = [-1]
    length = [0]
    cnt = [0]
    last = 0

    for ch in s:
        cur = len(nxt)
        nxt.append(dict())
        link.append(-1)
        length.append(length[last] + 1)
        cnt.append(1)
        p = last
        while p != -1 and ch not in nxt[p]:
            nxt[p][ch] = cur
            p = link[p]
        if p == -1:
            link[cur] = 0
        else:
            q = nxt[p][ch]
            if length[p] + 1 == length[q]:
                link[cur] = q
            else:
                clone = len(nxt)
                nxt.append(dict(nxt[q]))
                link.append(link[q])
                length.append(length[p] + 1)
                cnt.append(0)
                while p != -1 and nxt[p].get(ch) == q:
                    nxt[p][ch] = clone
                    p = link[p]
                link[q] = clone
                link[cur] = clone
        last = cur

    m = len(nxt)
    # Propagate endpos-set sizes up the suffix-link tree, children before parents.
    order = sorted(range(m), key=lambda v: length[v], reverse=True)
    for v in order:
        pl = link[v]
        if pl != -1:
            cnt[pl] += cnt[v]

    ans = 0
    for v in range(1, m):
        if cnt[v] >= k and length[v] > ans:
            ans = length[v]
    return ans

from typing import Sequence, Tuple


def max_treasure(
    n: int,
    treasure: Sequence[int],
    roads: Sequence[Tuple[int, int]],
    start: int,
) -> int:
    """Maximum total treasure collectible on a directed graph.

    See spec.md for the full statement. Approach: condense strongly connected
    components (each SCC can be fully looted), then take the longest weighted
    path in the resulting DAG starting from the component containing ``start``.
    Runs in O(n + m) with no recursion (iterative Kosaraju).
    """
    g = [[] for _ in range(n)]
    rg = [[] for _ in range(n)]
    for u, v in roads:
        g[u].append(v)
        rg[v].append(u)

    # ---- Kosaraju pass 1: iterative post-order over the forward graph. ----
    visited = [False] * n
    order = []
    for src in range(n):
        if visited[src]:
            continue
        visited[src] = True
        stack = [(src, 0)]
        while stack:
            node, i = stack.pop()
            if i < len(g[node]):
                stack.append((node, i + 1))
                w = g[node][i]
                if not visited[w]:
                    visited[w] = True
                    stack.append((w, 0))
            else:
                order.append(node)

    # ---- Kosaraju pass 2: assign components in reverse finish order. ----
    comp = [-1] * n
    c = 0
    for src in reversed(order):
        if comp[src] != -1:
            continue
        comp[src] = c
        stack = [src]
        while stack:
            node = stack.pop()
            for w in rg[node]:
                if comp[w] == -1:
                    comp[w] = c
                    stack.append(w)
        c += 1

    # Component weights.
    cw = [0] * c
    for i in range(n):
        cw[comp[i]] += treasure[i]

    # Condensation adjacency (deduplicated). Kosaraju numbers components in
    # topological order: every cross edge goes from a lower id to a higher id.
    cadj = [set() for _ in range(c)]
    for u, v in roads:
        cu, cv = comp[u], comp[v]
        if cu != cv:
            cadj[cu].add(cv)

    # Longest weighted path. Process components in reverse topological order
    # (descending id) so all successors are already resolved. All weights are
    # non-negative, so extending a path never hurts and stopping is the 0 case.
    dp = [0] * c
    for cc in range(c - 1, -1, -1):
        best = 0
        for sc in cadj[cc]:
            if dp[sc] > best:
                best = dp[sc]
        dp[cc] = cw[cc] + best

    return dp[comp[start]]

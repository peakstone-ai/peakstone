import random

from solution import max_treasure


# --------------------------------------------------------------------------
# Independent reference: O(n^3) transitive-closure SCCs + recursive DAG DP.
# Deliberately a different algorithm than the solution (no Kosaraju/Tarjan).
# Only used on small graphs.
# --------------------------------------------------------------------------
def _brute(n, treasure, roads, start):
    adj = [[] for _ in range(n)]
    for u, v in roads:
        adj[u].append(v)

    reach = [[False] * n for _ in range(n)]
    for s in range(n):
        seen = {s}
        stack = [s]
        while stack:
            x = stack.pop()
            for y in adj[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        for y in seen:
            reach[s][y] = True
        reach[s][s] = True

    comp = [-1] * n
    cid = 0
    for i in range(n):
        if comp[i] != -1:
            continue
        comp[i] = cid
        for j in range(n):
            if comp[j] == -1 and reach[i][j] and reach[j][i]:
                comp[j] = cid
        cid += 1

    cw = [0] * cid
    for i in range(n):
        cw[comp[i]] += treasure[i]

    cadj = [set() for _ in range(cid)]
    for u, v in roads:
        if comp[u] != comp[v]:
            cadj[comp[u]].add(comp[v])

    memo = {}

    def dp(cc):
        if cc in memo:
            return memo[cc]
        best = 0
        for sc in cadj[cc]:
            best = max(best, dp(sc))
        memo[cc] = cw[cc] + best
        return memo[cc]

    return dp(comp[start])


# --------------------------- basic / edge cases ---------------------------
def test_single_node_no_edges():
    assert max_treasure(1, [7], [], 0) == 7


def test_single_node_with_self_loop():
    assert max_treasure(1, [7], [(0, 0)], 0) == 7


def test_zero_value_node():
    assert max_treasure(1, [0], [], 0) == 0


def test_simple_chain():
    # 0 -> 1 -> 2, collect everything downstream
    treasure = [1, 10, 100]
    roads = [(0, 1), (1, 2)]
    assert max_treasure(3, treasure, roads, 0) == 111
    assert max_treasure(3, treasure, roads, 1) == 110
    assert max_treasure(3, treasure, roads, 2) == 100


def test_two_node_cycle_is_one_scc():
    # 0 <-> 1: both lootable from either start
    assert max_treasure(2, [3, 4], [(0, 1), (1, 0)], 0) == 7
    assert max_treasure(2, [3, 4], [(0, 1), (1, 0)], 1) == 7


def test_unreachable_treasure_excluded():
    # node 2 holds a fortune but is unreachable from 0
    treasure = [1, 1, 1000]
    roads = [(0, 1)]
    assert max_treasure(3, treasure, roads, 0) == 2


def test_pick_the_richer_branch():
    # 0 -> 1 (value 5) and 0 -> 2 (value 50); only one branch is on a path
    treasure = [1, 5, 50]
    roads = [(0, 1), (0, 2)]
    assert max_treasure(3, treasure, roads, 0) == 51


def test_branch_choice_favors_longer_sum():
    # 0 -> 1 -> 3 (1+2+100) vs 0 -> 2 (1+50) ; note 3 unreachable via 2
    treasure = [1, 2, 50, 100]
    roads = [(0, 1), (1, 3), (0, 2)]
    assert max_treasure(4, treasure, roads, 0) == 103


def test_scc_then_dag_tail():
    # {0,1,2} form a cycle (sum 6), then 2 -> 3 (value 100)
    treasure = [1, 2, 3, 100]
    roads = [(0, 1), (1, 2), (2, 0), (2, 3)]
    assert max_treasure(4, treasure, roads, 0) == 106
    assert max_treasure(4, treasure, roads, 3) == 100


def test_multi_edges_and_self_loops_ignored():
    treasure = [10, 20]
    roads = [(0, 1), (0, 1), (0, 0), (1, 1)]
    assert max_treasure(2, treasure, roads, 0) == 30


def test_diamond_shared_tail_counted_once():
    #   0 -> 1 -> 3
    #   0 -> 2 -> 3
    # node 3 must be counted once, not twice
    treasure = [1, 10, 20, 100]
    roads = [(0, 1), (0, 2), (1, 3), (2, 3)]
    assert max_treasure(4, treasure, roads, 0) == 1 + 20 + 100  # via 0->2->3


def test_start_in_middle_ignores_upstream():
    treasure = [1000, 1, 1]
    roads = [(0, 1), (1, 2)]
    # starting at 1, the rich node 0 is upstream and unreachable
    assert max_treasure(3, treasure, roads, 1) == 2


def test_two_cycles_joined():
    # cycle A {0,1} -> cycle B {2,3}
    treasure = [1, 1, 5, 5]
    roads = [(0, 1), (1, 0), (1, 2), (2, 3), (3, 2)]
    assert max_treasure(4, treasure, roads, 0) == 12
    assert max_treasure(4, treasure, roads, 2) == 10


# --------------------------- randomized fuzz ---------------------------
def test_random_small_graphs_match_brute():
    rng = random.Random(20260701)
    for _ in range(600):
        n = rng.randint(1, 8)
        treasure = [rng.randint(0, 12) for _ in range(n)]
        m = rng.randint(0, n * 2)
        roads = [(rng.randrange(n), rng.randrange(n)) for _ in range(m)]
        start = rng.randrange(n)
        expected = _brute(n, treasure, roads, start)
        assert max_treasure(n, treasure, roads, start) == expected, (
            n,
            treasure,
            roads,
            start,
        )


def test_random_dense_graphs_match_brute():
    rng = random.Random(4242)
    for _ in range(300):
        n = rng.randint(3, 7)
        treasure = [rng.randint(0, 20) for _ in range(n)]
        roads = []
        for u in range(n):
            for v in range(n):
                if u != v and rng.random() < 0.4:
                    roads.append((u, v))
        start = rng.randrange(n)
        expected = _brute(n, treasure, roads, start)
        assert max_treasure(n, treasure, roads, start) == expected


# --------------------------- larger / performance ---------------------------
def test_large_chain():
    n = 100_000
    treasure = [1] * n
    roads = [(i, i + 1) for i in range(n - 1)]
    assert max_treasure(n, treasure, roads, 0) == n
    assert max_treasure(n, treasure, roads, n // 2) == n - n // 2


def test_large_single_cycle():
    n = 100_000
    treasure = [1] * n
    roads = [(i, (i + 1) % n) for i in range(n)]
    # entire cycle is one SCC, all lootable from anywhere
    assert max_treasure(n, treasure, roads, 0) == n
    assert max_treasure(n, treasure, roads, 12345) == n


def test_large_deep_no_recursion_limit():
    # A long chain would overflow a naive recursive SCC / DP; must be iterative.
    n = 50_000
    treasure = [2] * n
    roads = [(i, i + 1) for i in range(n - 1)]
    assert max_treasure(n, treasure, roads, 0) == 2 * n


def test_large_binary_tree_longest_root_to_leaf():
    # complete binary tree, node i -> 2i+1, 2i+2; value = 1 everywhere.
    # longest root path collects (deepest level + 1) nodes.
    n = 1 << 16  # 65536 nodes
    treasure = [1] * n
    roads = []
    for i in range(n):
        for ch in (2 * i + 1, 2 * i + 2):
            if ch < n:
                roads.append((i, ch))
    # expected = number of levels on the deepest greedy root-to-leaf walk
    levels = 0
    idx = 0
    while idx < n:
        levels += 1
        idx = 2 * idx + 1
    assert max_treasure(n, treasure, roads, 0) == levels

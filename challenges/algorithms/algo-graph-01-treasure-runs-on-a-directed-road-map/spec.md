# Treasure runs on a directed road map

An adventurer roams a network of `n` outposts connected by **one-way** roads.
Outpost `i` holds `treasure[i]` gold (a **non-negative** integer). Starting at
outpost `start`, the adventurer may follow roads for as long as they like — even
driving around in circles — and **loots each outpost the first time they visit
it** (revisiting an already-looted outpost yields nothing).

Compute the **maximum total gold** the adventurer can collect.

Implement a file **`solution.py`** with:

```python
def max_treasure(n: int, treasure: Sequence[int],
                 roads: Sequence[Tuple[int, int]], start: int) -> int:
    ...
```

## Input

- `n` — number of outposts, labeled `0 .. n-1`  (`1 <= n`).
- `treasure` — a list of `n` non-negative integers; `treasure[i]` is the gold at outpost `i`.
- `roads` — a list of directed edges `(u, v)` meaning there is a one-way road **from `u` to `v`**.
  Roads may include **self-loops** `(u, u)` and **duplicate** edges.
- `start` — the outpost the adventurer begins at (`0 <= start < n`).

## Output

Return a single integer: the maximum gold collectible on any walk that begins at
`start`, counting each outpost's gold **at most once**.

## What "collect" means

Because roads are one-way, a walk visits a sequence of outposts and loots the
distinct ones it touches. Two consequences drive the problem:

- If a set of outposts is **mutually reachable** (you can get from any one to any
  other and back — a strongly connected group), then once you enter the group you
  can tour **all** of its outposts, so their gold is collected together.
- Once you leave such a group along a road, you can never return to it (otherwise
  it would have been part of the group). So the walk, viewed at the level of these
  groups, moves **strictly forward** through the road network.

Gold is never negative, so lingering to loot more is never harmful; the only real
decision is **which forward branch to commit to**.

## Examples

```python
# 0 -> 1 -> 2, values 1,10,100
assert max_treasure(3, [1, 10, 100], [(0, 1), (1, 2)], 0) == 111
assert max_treasure(3, [1, 10, 100], [(0, 1), (1, 2)], 2) == 100

# 0 <-> 1 is one mutually-reachable group: loot both from either start
assert max_treasure(2, [3, 4], [(0, 1), (1, 0)], 0) == 7

# unreachable fortune is excluded
assert max_treasure(3, [1, 1, 1000], [(0, 1)], 0) == 2

# {0,1,2} form a cycle (1+2+3), then 2 -> 3 worth 100
assert max_treasure(4, [1, 2, 3, 100], [(0, 1), (1, 2), (2, 0), (2, 3)], 0) == 106

# a shared downstream outpost is counted once, not twice
#   0->1->3 and 0->2->3
assert max_treasure(4, [1, 10, 20, 100], [(0, 1), (0, 2), (1, 3), (2, 3)], 0) == 121

# you must pick the richer of two mutually-exclusive branches
assert max_treasure(3, [1, 5, 50], [(0, 1), (0, 2)], 0) == 51
```

## Constraints & notes

- Only outposts **reachable from `start`** can ever be looted.
- Self-loops and duplicate roads must be handled gracefully.
- The graph can be **large and deep**: expect up to about `10^5` outposts and
  `2 * 10^5` roads, including a single chain that long. A solution whose recursion
  depth grows with the graph will overflow — use an **iterative** approach. An
  overall `O(n + m)` algorithm is expected.
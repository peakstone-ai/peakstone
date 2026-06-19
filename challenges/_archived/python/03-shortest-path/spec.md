# BFS Shortest Path Length

Implement a file **`solution.py`** containing a function:

```python
def shortest_path_len(graph: dict[str, list[str]], start: str, goal: str) -> int:
    ...
```

`graph` is an **unweighted directed** adjacency mapping: each key is a node, and
its value is the list of nodes reachable by one edge from it. Return the number
of edges on a shortest path from `start` to `goal`.

Rules:

- Return `0` when `start == goal`.
- Return `-1` when `goal` is unreachable from `start`.
- Edges count as length 1 each; find the minimum total via breadth-first search.
- A node may appear as a neighbor without having its own key in `graph`
  (treat it as having no outgoing edges).
- The graph may contain cycles; do not loop forever.

Examples:

```python
g = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
shortest_path_len(g, "a", "d") == 2
shortest_path_len(g, "a", "a") == 0
shortest_path_len(g, "d", "a") == -1
```

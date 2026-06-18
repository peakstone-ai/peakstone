# Dijkstra shortest paths (heapq)

Implement **`solution.py`** with:

```python
def dijkstra(graph: dict[str, list[tuple[str, float]]], start: str) -> dict[str, float]:
    ...
```

Compute the **shortest-path distance** from `start` to every reachable node in a
weighted **directed** graph.

- `graph[u]` is a list of `(v, weight)` edges from `u` to `v`. Weights are
  non-negative.
- Return a dict mapping each **reachable** node to its minimum total distance from
  `start`. `start` itself maps to `0.0`.
- **Unreachable nodes must be omitted** from the result (do not include them with
  `inf`).
- A node that appears only as an edge target (never as a key in `graph`) is a
  valid node with no outgoing edges.
- Use the standard library only — implement Dijkstra's algorithm with
  **`heapq`** as the priority queue. Do **not** use networkx or any third-party
  library here.

Example:

```python
g = {
    "a": [("b", 1.0), ("c", 4.0)],
    "b": [("c", 2.0), ("d", 5.0)],
    "c": [("d", 1.0)],
    "d": [],
}
dijkstra(g, "a")
# {"a": 0.0, "b": 1.0, "c": 3.0, "d": 4.0}

dijkstra({"a": [("b", 2.0)], "b": [], "island": [("a", 1.0)]}, "a")
# {"a": 0.0, "b": 2.0}   # "island" is unreachable from "a", omitted
```

# Detect cycle in a directed graph

Implement **`solution.go`** in `package challenge` exporting:

```go
func HasCycle(graph map[string][]string) bool
```

The graph is given as an adjacency map: each key is a node, and its value is the slice of
nodes it has directed edges to. Return `true` if the directed graph contains **any cycle**,
and `false` otherwise.

Rules:

- A **self-loop** (`"a" -> "a"`) counts as a cycle.
- A neighbor that does not appear as a key in the map is a valid node with no outgoing edges.
- An empty map (or `nil`) has no cycle → `false`.
- Duplicate edges are allowed and must not break detection.

Examples:

- `HasCycle(map[string][]string{"a": {"b"}, "b": {"c"}, "c": {}})` → `false` (a DAG)
- `HasCycle(map[string][]string{"a": {"a"}})` → `true` (self-loop)
- `HasCycle(map[string][]string{"a": {"b"}, "b": {"c"}, "c": {"a"}})` → `true` (3-node cycle)
- `HasCycle(map[string][]string{})` → `false`

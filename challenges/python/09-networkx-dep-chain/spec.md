# Longest dependency chain (networkx)

Implement **`solution.py`** with:

```python
def longest_dependency_chain(deps: dict[str, list[str]]) -> int:
    ...
```

`deps` describes a **DAG** of build/task dependencies: `deps[x]` is the list of
**prerequisites** of `x` (the things that must be done before `x`).

Return the **length of the longest dependency chain**, measured as the **number of
nodes** in that chain (a single node with no dependencies has a chain length of 1).

Details:

- Every key in `deps` is a node. Prerequisites listed in the values are also nodes
  even if they never appear as keys (they implicitly have no prerequisites).
- The empty graph (`deps == {}`) has a longest-chain length of `0`.
- The input is guaranteed to be acyclic.
- Use **networkx**: build a `DiGraph` and use a topological/DAG routine such as
  `networkx.dag_longest_path` (note that `dag_longest_path` returns a list of
  nodes, and you want its node count).

Example:

```python
longest_dependency_chain({"a": ["b"], "b": ["c"], "c": []})
# 3   (chain c -> b -> a)

longest_dependency_chain({"a": ["b", "c"], "b": ["d"], "c": [], "d": []})
# 3   (chain d -> b -> a)

longest_dependency_chain({"solo": []})
# 1
```

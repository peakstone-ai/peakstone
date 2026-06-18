# Top-N rows per group (pandas)

Implement **`solution.py`** with:

```python
import pandas as pd

def top_n_per_group(df: pd.DataFrame, group_col: str, value_col: str, n: int) -> pd.DataFrame:
    ...
```

Given a DataFrame `df`, return a new DataFrame containing, for each group defined
by `group_col`, the **top `n` rows ranked by `value_col` in descending order**.

Requirements:

- All original columns must be preserved (do not drop, rename, or reorder columns).
- Within each group, rows are ordered by `value_col` **descending**. Groups that
  have fewer than `n` rows contribute all of their rows.
- The result is ordered by group, and within each group by `value_col` descending.
  Group order follows the order in which each group first appears in `df`.
- Ties in `value_col` may be broken arbitrarily, but the number of rows returned
  per group must be exactly `min(n, group_size)`.
- The returned DataFrame must use a clean `RangeIndex` (`0..len-1`) — call
  `reset_index(drop=True)` on the result.
- Do not mutate the input `df`.

Use pandas (e.g. `sort_values` + `groupby(...).head(n)`).

Example:

```python
df = pd.DataFrame({
    "team": ["a", "a", "a", "b", "b"],
    "name": ["x", "y", "z", "p", "q"],
    "score": [10, 30, 20, 5, 15],
})
top_n_per_group(df, "team", "score", 2)
#   team name  score
# 0    a    y     30
# 1    a    z     20
# 2    b    q     15
# 3    b    p      5
```

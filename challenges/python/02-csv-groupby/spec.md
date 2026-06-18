# CSV Group Sum

Implement a file **`solution.py`** containing a function:

```python
def group_sum(csv_text: str, key_col: str, val_col: str) -> dict[str, float]:
    ...
```

Parse `csv_text` as CSV and return a dictionary mapping each distinct value in
column `key_col` to the **sum** of column `val_col` for all rows with that key.

Rules:

- The **first non-blank line** is the header row naming the columns.
- Columns are comma-separated. `key_col` and `val_col` name two of those columns.
- Values in `val_col` are numeric (int or float); sum them as floats.
- **Ignore blank lines** anywhere in the input (including trailing newlines).
- If the input has only a header (or is empty), return an empty dict `{}`.
- You may assume `key_col` and `val_col` exist in the header.

Example:

```python
csv_text = "name,amount\\nalice,10\\nbob,5\\nalice,2.5\\n"
group_sum(csv_text, "name", "amount") == {"alice": 12.5, "bob": 5.0}
```

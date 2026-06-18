# Transactional key-value store

Implement a file **`solution.py`** containing a class `KVStore` that behaves like an in-memory
key-value map with **nested transactions**.

```python
class KVStore:
    def __init__(self): ...
    def get(self, key):          ...   # current value, or None if absent
    def set(self, key, value):   ...
    def delete(self, key):       ...   # remove key (no-op if absent)
    def keys(self):              ...   # sorted list of currently-visible keys
    def __len__(self):           ...   # number of currently-visible keys

    def begin(self):    ...            # open a new (nested) transaction
    def commit(self):   ...            # merge the innermost open transaction into its parent
    def rollback(self): ...            # discard the innermost open transaction
```

## Semantics

- With **no open transaction**, `set`/`delete` mutate the committed store directly.
- `begin()` opens a transaction. Transactions **nest**: a second `begin()` opens a child of the
  first. All `set`/`delete` calls apply to the **innermost** open transaction only.
- `get`, `keys`, and `__len__` always reflect the **currently-visible** state: the committed store
  overlaid by every open transaction in order (innermost wins). A key `delete`d in an open
  transaction is invisible even if it exists in the committed store.
- `commit()` merges the innermost transaction's changes (both sets and deletes) into its parent
  (the enclosing transaction, or the committed store if it was the outermost). The transaction is
  then closed.
- `rollback()` discards the innermost transaction's changes entirely and closes it.
- `commit()` or `rollback()` with **no open transaction** must raise `RuntimeError`.
- `keys()` returns the visible keys in **sorted order**.

## Example

```python
s = KVStore()
s.set("a", 1)
s.begin()
s.set("a", 2)
s.set("b", 3)
assert s.get("a") == 2          # innermost transaction wins
s.begin()
s.delete("a")
assert s.get("a") is None       # deleted in the inner transaction
assert s.get("b") == 3          # still visible from the outer transaction
s.rollback()                    # discard the inner transaction
assert s.get("a") == 2          # back to the outer transaction's value
s.commit()                      # merge outer transaction into the committed store
assert s.get("a") == 2 and s.get("b") == 3
assert s.keys() == ["a", "b"]
```

# Running median (sortedcontainers)

Implement **`solution.py`** with a class:

```python
class RunningMedian:
    def __init__(self) -> None:
        ...

    def add(self, x: float) -> None:
        ...

    def median(self) -> float:
        ...
```

A streaming median tracker:

- `add(x)` inserts a value into the running collection.
- `median()` returns the median of all values added so far.
  - For an **odd** number of values, the median is the single middle value.
  - For an **even** number of values, the median is the **average of the two
    middle values**.
  - Calling `median()` before any values are added must raise a `ValueError`.

Use **`sortedcontainers.SortedList`** to keep values ordered so each insertion is
O(log n) and the middle element(s) can be indexed directly.

Example:

```python
m = RunningMedian()
m.add(5); m.median()   # 5
m.add(1); m.median()   # 3.0  (avg of 1 and 5)
m.add(3); m.median()   # 3    (middle of [1, 3, 5])
m.add(3); m.median()   # 3.0  (avg of two middle of [1, 3, 3, 5])
```

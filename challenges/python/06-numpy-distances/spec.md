# Pairwise distances (numpy)

Implement **`solution.py`** with:

```python
import numpy as np

def pairwise_distances(points: np.ndarray) -> np.ndarray:
    ...
```

`points` is a 2-D array of shape `(n, d)` (n points in d dimensions). Return an `(n, n)`
array where entry `[i, j]` is the Euclidean distance between point `i` and point `j`.

- The result must be a NumPy array (`np.ndarray`), symmetric, with a zero diagonal.
- Use NumPy vectorization (no Python `for` loops over point pairs).
- Example: for `[[0, 0], [3, 4]]` the result is `[[0, 5], [5, 0]]`.

# BigCodeBench/39

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `numpy`, `matplotlib`, `scipy`.

```python
import numpy as np
from scipy.stats import ttest_1samp
import matplotlib.pyplot as plt

# Constants
ALPHA = 0.05


def task_func(data_matrix):
    """
    Calculate the mean value of each row in a 2D data matrix, run a t-test from a sample against the population value, and record the mean values that differ significantly.
    - Create a lineplot with the mean of rows in red. Its label is 'Means'.
    - Create a line plot with the significant_indices (those with a pvalue less than ALPHA) on the x-axis and the corresponding means on the y-axis. This plot should be blue. Its label is 'Significant Means'.
    - Create an horizontal line which represent the mean computed on the whole 2D matrix. It should be in green. Its label is 'Population Mean'.

    Parameters:
    data_matrix (numpy.array): The 2D data matrix.

    Returns:
    tuple: A tuple containing:
        - list: A list of indices of the means that are significantly different from the population mean.
        - Axes: The plot showing the means and significant means.

    Requirements:
    - numpy
    - scipy.stats.ttest_1samp
    - matplotlib.pyplot

    Example:
    >>> data = np.array([[6, 8, 1, 3, 4], [-1, 0, 3, 5, 1]])
    >>> indices, ax = task_func(data)
    >>> print(indices)
    []

    Example 2:
    >>> data = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    >>> indices, ax = task_func(data)
    >>> print(indices)
    []
    """
```

<!-- imported from BigCodeBench (BigCodeBench/39) -->

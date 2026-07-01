# BigCodeBench/42

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `pandas`, `matplotlib`, `sklearn`.

```python
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA


def task_func(data_matrix, n_components=2):
    """
    Apply PCA with n_components components to a 2D data matrix, calculate the mean value of each component, and then return the cumulative explained variance of the components in a plot.
    - The function returns a dataframe with columns 'Component 1', 'Component 2', ... etc.
    - Each row of the dataframe correspond to a row of the original matrix mapped in the PCA space.
    - The dataframe should also include a column 'Mean' which is the average value of each component value per row
    - Create a plot of the cumulative explained variance.
        - the xlabel should be 'Number of Components' and the ylabel 'Cumulative Explained Variance'

    Parameters:
    data_matrix (numpy.array): The 2D data matrix.

    Returns:
    tuple:
        - pandas.DataFrame: A DataFrame containing the PCA transformed data and the mean of each component.
        - matplotlib.axes._axes.Axes: A plot showing the cumulative explained variance of the components.

    Requirements:
    - pandas
    - matplotlib.pyplot
    - sklearn.decomposition

    Example:
    >>> import numpy as np
    >>> data = np.array([[6, 8, 1, 3, 4], [-1, 0, 3, 5, 1]])
    >>> df, ax = task_func(data)
    >>> print(df["Mean"])
    0    2.850439
    1   -2.850439
    Name: Mean, dtype: float64
    """
```

<!-- imported from BigCodeBench (BigCodeBench/42) -->

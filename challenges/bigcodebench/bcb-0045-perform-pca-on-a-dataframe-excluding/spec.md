# BigCodeBench/45

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `pandas`, `matplotlib`, `numpy`, `sklearn`, `seaborn`.

```python
import pandas as pd
import numpy as np
from sklearn.decomposition import PCA
import seaborn as sns
import matplotlib.pyplot as plt

def task_func(df: pd.DataFrame):
    """
    Perform PCA on a DataFrame (excluding non-numeric columns) and draw a scatter plot of the first two main components. The principal columns should be name 'Component 1' and 'Component 2'.
    Missing values are replaced by column's average.

    Parameters:
    df (DataFrame): The pandas DataFrame.

    Returns:
    DataFrame: A pandas DataFrame with the first two principal components. The columns should be 'principal component 1' and 'principal component 2'.
    Axes: A matplotlib Axes object representing the scatter plot. The xlabel should be 'principal component' and the ylabel 'principal component 2'.

    Requirements:
    - pandas
    - numpy
    - sklearn.decomposition.PCA
    - seaborn
    - matplotlib

    Example:
    >>> df = pd.DataFrame([[1,2,3],[4,5,6],[7.0,np.nan,9.0]], columns=["c1","c2","c3"])
    >>> principalDf, ax = task_func(df)
    >>> print(principalDf)
       Component 1  Component 2
    0     4.450915    -0.662840
    1    -0.286236     1.472436
    2    -4.164679    -0.809596
    """
```

<!-- imported from BigCodeBench (BigCodeBench/45) -->

import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import skew


def task_func(data_matrix):
    """
    Calculate the skew of each row in a 2D data matrix and plot the distribution.

    Parameters:
    - data_matrix (numpy.array): The 2D data matrix.

    Returns:
    pandas.DataFrame: A DataFrame containing the skewness of each row. The skweness is stored in a new column which name is 'Skewness'.
    matplotlib.axes.Axes: The Axes object of the plotted distribution.

    Requirements:
    - pandas
    - matplotlib.pyplot
    - scipy.stats.skew

    Example:
    >>> import numpy as np
    >>> data = np.array([[6, 8, 1, 3, 4], [-1, 0, 3, 5, 1]])
    >>> df, ax = task_func(data)
    >>> print(df)
       Skewness
    0  0.122440
    1  0.403407
    """
    skewness = skew(data_matrix, axis=1)
    df = pd.DataFrame(skewness, columns=["Skewness"])
    plt.figure(figsize=(10, 5))
    df["Skewness"].plot(kind="hist", title="Distribution of Skewness")
    return df, plt.gca()
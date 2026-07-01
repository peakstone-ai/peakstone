import numpy as np
from scipy import stats
import matplotlib.pyplot as plt

TARGET_VALUES = np.array([1, 3, 4])

def task_func(df):
    """
    Replace all elements in DataFrame columns that do not exist in the TARGET_VALUES array with zeros, then perform a Box-Cox transformation on each column (if data is not constant, add 1 to account for zeros) and display the resulting KDE plots.

    Parameters:
        - df (pandas.DataFrame): The input pandas DataFrame with positive values.

    Returns:
        - pandas.DataFrame: The transformed DataFrame after Box-Cox transformation.
        - matplotlib.figure.Figure: Figure containing KDE plots of the transformed columns.

    Requirements:
    - numpy
    - scipy.stats
    - matplotlib.pyplot

    Example:
    >>> np.random.seed(42)
    >>> df = pd.DataFrame(np.random.randint(1, 10, size=(100, 5)), columns=list('ABCDE'))  # Values should be positive for Box-Cox
    >>> transformed_df, fig = task_func(df)
    >>> print(transformed_df.head(2))
              A         B    C    D         E
    0  0.000000  0.566735  0.0  0.0  0.000000
    1  0.530493  0.000000  0.0  0.0  0.607007
    """
    # Ensure the DataFrame contains only positive values
    if (df <= 0).any().any():
        raise ValueError("Input DataFrame should contain only positive values.")

    df = df.applymap(lambda x: x if x in TARGET_VALUES else 0)

    transformed_df = pd.DataFrame()

    fig, ax = plt.subplots()

    for column in df.columns:
        # Check if data is constant
        if df[column].nunique() == 1:
            transformed_df[column] = df[column]
        else:
            transformed_data, _ = stats.boxcox(
                df[column] + 1
            )  # Add 1 since the are some null values
            transformed_df[column] = transformed_data

            # Using matplotlib's kde method to plot the KDE
            kde = stats.gaussian_kde(transformed_df[column])
            x_vals = np.linspace(
                min(transformed_df[column]), max(transformed_df[column]), 1000
            )
            ax.plot(x_vals, kde(x_vals), label=column)

    ax.legend()
    plt.show()
    return transformed_df, fig
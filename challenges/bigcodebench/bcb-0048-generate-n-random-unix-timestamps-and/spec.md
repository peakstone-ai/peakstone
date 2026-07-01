# BigCodeBench/48

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `datetime`, `random`, `matplotlib`, `time`.

```python
import time
from datetime import datetime
import random
import matplotlib.pyplot as plt

# Constants
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def task_func(n, output_path=None):
    """
    Generate n random Unix timestamps and convert them to strings formatted as UTC DATE_FORMAT.
    Plot a histogram of the distribution of the generated timestamps. If an output path is provided,
    save the histogram to the specified path. Otherwise, display the plot.

    Parameters:
    n (int): The number of timestamps to generate.
    output_path (str, optional): Path to save the histogram plot. Defaults to None.

    Returns:
    list: The list of n formatted timestamps.

    Requirements:
    - time
    - datetime
    - random
    - matplotlib.pyplot

    Example:
    >>> random.seed(42)
    >>> timestamps = task_func(n=3, output_path=None)
    >>> print(timestamps)
    ['2013-07-06 20:56:46', '1977-07-29 23:34:23', '1971-09-14 11:29:44']
    """
```

<!-- imported from BigCodeBench (BigCodeBench/48) -->

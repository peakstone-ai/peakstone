# BigCodeBench/11

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `numpy`, `itertools`, `random`.

```python
import numpy as np
import itertools
import random


def task_func(T1, max_value=100):
    """
    Converts elements in 'T1', a tuple of tuples containing string representations 
    of integers, to integers and creates a list of random integers. The size of the 
    list equals the sum of these integers. Returns the 25th, 50th, and 75th percentiles 
    of this list.

    Parameters:
    T1 (tuple of tuple of str): A tuple of tuples, each containing string representations of integers.
    max_value (int): The upper bound for random number generation, exclusive. Default is 100.
    
    Returns:
    tuple: A tuple (p25, p50, p75) representing the 25th, 50th, and 75th percentiles of the list.

    Requirements:
    - numpy
    - itertools
    - random
    
    Example:
    >>> import random
    >>> random.seed(42)
    >>> T1 = (('13', '17', '18', '21', '32'), ('07', '11', '13', '14', '28'), ('01', '05', '06', '08', '15', '16'))
    >>> percentiles = task_func(T1)
    >>> print(percentiles)
    (24.0, 48.0, 77.0)
    """
```

<!-- imported from BigCodeBench (BigCodeBench/11) -->

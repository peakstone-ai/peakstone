# BigCodeBench/0

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `random`, `itertools`.

```python
import itertools
from random import shuffle

def task_func(numbers=list(range(1, 3))):
    """
    Calculates the average of the sums of absolute differences between each pair of consecutive numbers 
    for all permutations of a given list. Each permutation is shuffled before calculating the differences.

    Args:
    - numbers (list): A list of numbers. Default is numbers from 1 to 10.
    
    Returns:
    float: The average of the sums of absolute differences for each shuffled permutation of the list.

    Requirements:
    - itertools
    - random.shuffle

    Example:
    >>> result = task_func([1, 2, 3])
    >>> isinstance(result, float)
    True
    """
```

<!-- imported from BigCodeBench (BigCodeBench/0) -->

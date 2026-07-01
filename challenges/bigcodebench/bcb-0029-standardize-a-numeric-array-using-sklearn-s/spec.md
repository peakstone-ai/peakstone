# BigCodeBench/29

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `base64`, `numpy`, `sklearn`.

```python
from sklearn.preprocessing import StandardScaler
import numpy as np
import base64

def task_func(data):
    """
    Standardize a numeric array using sklearn's StandardScaler and encode the standardized data in base64 format as an ASCII string.
    
    Parameters:
    - data (numpy.ndarray): The numpy array to standardize and encode.
    
    Returns:
    - str: The base64-encoded ASCII string representation of the standardized data.
    
    Requirements:
    - sklearn.preprocessing.StandardScaler
    - numpy
    - base64
    
    Example:
    >>> data = np.array([[0, 0], [0, 0], [1, 1], [1, 1]])
    >>> encoded_data = task_func(data)
    >>> print(encoded_data)
    W1stMS4gLTEuXQogWy0xLiAtMS5dCiBbIDEuICAxLl0KIFsgMS4gIDEuXV0=
    """
```

<!-- imported from BigCodeBench (BigCodeBench/29) -->

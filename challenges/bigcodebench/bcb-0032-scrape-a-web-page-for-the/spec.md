# BigCodeBench/32

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; define `task_func` at module level.

Allowed libraries: `bs4`, `requests`.

```python
import requests
from bs4 import BeautifulSoup

def task_func(url, tag):
    """
    Scrape a web page for the first occurrence of a specified HTML tag and return its text content.

    Parameters:
    url (str): The URL of the website to scrape.
    tag (str): The HTML tag to find and retrieve text from.

    Returns:
    str: The text content of the specified HTML tag if found, otherwise returns None.

    Requirements:
    - requests
    - bs4.BeautifulSoup

    Example:
    >>> task_func("https://www.google.com/", "title")
    'Google'
    """
```

<!-- imported from BigCodeBench (BigCodeBench/32) -->

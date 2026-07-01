# HumanEval/50

Implement a file **`solution.py`** that completes the function below. Keep the given name and signature; your file must define it at module level.

```python


def encode_shift(s: str):
    """
    returns encoded string by shifting every character by 5 in the alphabet.
    """
    return "".join([chr(((ord(ch) + 5 - ord("a")) % 26) + ord("a")) for ch in s])


def decode_shift(s: str):
    """
    takes as input string encoded with encode_shift function. Returns decoded string.
    """
```

<!-- imported from OpenAI HumanEval (HumanEval/50) -->

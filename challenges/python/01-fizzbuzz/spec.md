# FizzBuzz

Implement a file **`solution.py`** containing a function:

```python
def fizzbuzz(n: int) -> list[str]:
    ...
```

It returns a list of length `n` for the numbers `1..n` where:

- multiples of 3 become `"Fizz"`,
- multiples of 5 become `"Buzz"`,
- multiples of both 3 and 5 become `"FizzBuzz"`,
- every other number becomes its decimal string (e.g. `"7"`).

Example: `fizzbuzz(5) == ["1", "2", "Fizz", "4", "Buzz"]`.
Return an empty list when `n <= 0`.

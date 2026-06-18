# Self-repair: Roman numeral parser

The workspace contains a buggy `solution.py` with:

```python
def roman_to_int(s: str) -> int: ...
```

It should convert a Roman numeral string to its integer value, including **subtractive**
forms (`IV`=4, `IX`=9, `XL`=40, `XC`=90, `CD`=400, `CM`=900). The current implementation just
sums each symbol, so subtractive cases are wrong.

Run the tests to see the failures, fix `solution.py`, and re-run until all tests pass.

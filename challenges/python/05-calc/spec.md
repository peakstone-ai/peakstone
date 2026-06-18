# Arithmetic Expression Evaluator

Implement a file **`solution.py`** containing a function:

```python
def evaluate(expr: str) -> float:
    ...
```

Evaluate an arithmetic expression given as a string and return its value as a
`float`.

Supported syntax:

- Binary operators `+`, `-`, `*`, `/` with standard precedence
  (`*` and `/` bind tighter than `+` and `-`) and left-to-right associativity.
- Parentheses `(` ... `)` for grouping.
- Unary plus and minus, e.g. `-3`, `-(2 + 1)`, `2 * -3`.
- Integer and float literals, e.g. `42`, `3.14`, `.5`, `10.`.
- Arbitrary surrounding / internal whitespace, which is ignored.

Requirements:

- Return the numeric result as a `float`. For example
  `evaluate("1 + 2 * 3") == 7.0` and `evaluate("(1 + 2) * 3") == 9.0`.
- Implement a real parser/evaluator that respects precedence and parentheses.
  **Do not** use `eval`, `exec`, or similar (the harness may inspect for this).
- Raise `ValueError` on malformed input. Malformed includes: empty / whitespace-only
  input, unbalanced parentheses, a missing operand or operator (e.g. `"1 +"`,
  `"1 2"`, `"* 3"`), and unexpected characters.
- Division by zero should raise an error (a `ZeroDivisionError` or `ValueError`
  is acceptable).

Examples:

```python
evaluate("2 + 3 * 4")      # 14.0
evaluate("(2 + 3) * 4")    # 20.0
evaluate("10 / 4")         # 2.5
evaluate("-3 + 2")         # -1.0
evaluate("2 * (1 + -1.5)") # -1.0
```

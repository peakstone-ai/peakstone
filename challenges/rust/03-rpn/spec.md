# Evaluate RPN

Implement the library file **`src/lib.rs`** exposing:

```rust
pub fn eval_rpn(tokens: &[&str]) -> Result<f64, String>
```

Evaluate a [Reverse Polish Notation](https://en.wikipedia.org/wiki/Reverse_Polish_notation)
expression given as a slice of tokens. Each token is either:

- a number that parses as `f64`, or
- one of the four binary operators `+`, `-`, `*`, `/`.

Evaluation uses a stack: push numbers; for an operator, pop the top two values
`b` (top) then `a` (next) and push the result of `a OP b`. After consuming all
tokens, exactly one value must remain — that value is the result.

Return `Ok(value)` on success, or `Err(message)` (any non-empty message) on
malformed input:

- **too few operands** — an operator with fewer than two values on the stack.
- **leftover operands** — more than one value remains after all tokens consumed
  (or zero tokens / empty input, which leaves no value).
- **unknown token** — a token that is neither a valid `f64` nor a known operator.
- **division by zero** — a `/` whose right operand `b` is `0.0`.

Note: operator order matters for non-commutative operators. For `["3", "4", "-"]`
the result is `3 - 4 = -1.0`, and for `["8", "2", "/"]` it is `8 / 2 = 4.0`.

Examples:

- `eval_rpn(&["2", "3", "+"])` → `Ok(5.0)`
- `eval_rpn(&["5", "1", "2", "+", "4", "*", "+", "3", "-"])` → `Ok(14.0)` (precedence-via-RPN)
- `eval_rpn(&["3", "4", "-"])` → `Ok(-1.0)`
- `eval_rpn(&["1", "+"])` → `Err(..)` (too few operands)
- `eval_rpn(&["1", "2"])` → `Err(..)` (leftover operands)
- `eval_rpn(&["1", "foo", "+"])` → `Err(..)` (unknown token)
- `eval_rpn(&["1", "0", "/"])` → `Err(..)` (division by zero)

Use only the standard library. Tests live in `tests/` and call it as
`challenge::eval_rpn`.

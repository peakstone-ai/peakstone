# Balanced brackets

Implement the library file **`src/lib.rs`** exposing:

```rust
pub fn is_balanced(input: &str) -> bool
```

Return `true` if and only if the brackets `()`, `[]`, and `{}` in `input` are
correctly balanced and nested. Every opening bracket must be closed by a matching
closing bracket in the right order. Any closing bracket must match the most
recently opened, still-unclosed bracket.

- Non-bracket characters are ignored.
- The empty string is balanced (returns `true`).

Examples:

- `is_balanced("")` → `true`
- `is_balanced("()[]{}")` → `true`
- `is_balanced("([{}])")` → `true`
- `is_balanced("(a + [b * c]) - {d}")` → `true`
- `is_balanced("(]")` → `false`
- `is_balanced("([)]")` → `false`
- `is_balanced("(")` → `false`
- `is_balanced(")(")` → `false`

Tests live in `tests/` and call it as `challenge::is_balanced`.

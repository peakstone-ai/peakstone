# JSON parser to a typed value

Implement the library file **`src/lib.rs`** exposing a parser for a subset of JSON:

```rust
pub fn parse(input: &str) -> Result<Value, ParseError>

pub enum Value {
    Null,
    Bool(bool),
    Number(f64),
    Str(String),
    Array(Vec<Value>),
    Object(Vec<(String, Value)>),
}

pub struct ParseError { /* your fields — e.g. a message and position */ }
```

Derive `Debug`, `Clone`, and `PartialEq` for `Value` so it can be compared in tests.

Parse a single JSON value from `input` and return it as a `Value`, or `Err(ParseError)` if the
input is not valid. Support:

- **Literals**: `null`, `true`, `false`.
- **Numbers**: parsed as `f64` (integers, negatives, decimals, and exponents like `1e3`).
- **Strings**: double-quoted, with the escapes `\" \\ \/ \n \t \r \b \f` and `\uXXXX`.
- **Arrays**: `[`, comma-separated values, `]`. May be empty (`[]`).
- **Objects**: `{`, comma-separated `"key": value` members, `}`. May be empty (`{}`). **Preserve
  member order** exactly as it appears in the input (hence `Vec<(String, Value)>`, not a map).
- **Whitespace** (spaces, tabs, newlines, carriage returns) is allowed and ignored between tokens.

Errors (return `Err`, do not panic):
- malformed tokens, unterminated strings, missing `:`/`,`/closing brackets;
- **trailing characters** after a complete value (e.g. `"null null"` is an error).

Tests live in `tests/` and call `challenge::parse` and `challenge::Value`.

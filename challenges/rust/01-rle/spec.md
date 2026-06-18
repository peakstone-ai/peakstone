# Run-length encoding

Implement the library file **`src/lib.rs`** exposing:

```rust
pub fn run_length_encode(input: &str) -> String
```

Encode consecutive runs of the same character as `<char><count>`. A single character still
gets a count of `1`.

- `run_length_encode("aaabbc")` → `"a3b2c1"`
- `run_length_encode("")` → `""`
- `run_length_encode("abc")` → `"a1b1c1"`

Tests live in `tests/` and call it as `challenge::run_length_encode`.

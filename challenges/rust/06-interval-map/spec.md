# Generic interval map

Implement the library file **`src/lib.rs`** exposing a generic structure that maps integer
intervals to values:

```rust
pub struct IntervalMap<T> { /* ... */ }

impl<T> IntervalMap<T> {
    pub fn new() -> Self;
    pub fn insert(&mut self, start: i64, end: i64, value: T);
    pub fn get(&self, point: i64) -> Option<&T>;
    pub fn get_all(&self, point: i64) -> Vec<&T>;
}
```

Intervals are **half-open**: `[start, end)` covers every `p` with `start <= p < end`.

- **`insert(start, end, value)`** records that the half-open interval `[start, end)` maps to
  `value`. If `start >= end` the range is empty and the call is a **no-op**. Intervals may overlap.
- **`get(point)`** returns the value of the **most recently inserted** interval that covers `point`,
  or `None` if no interval covers it. (Newest insert wins on overlap.)
- **`get_all(point)`** returns references to the values of **all** intervals covering `point`,
  ordered **most-recently-inserted first**. Empty `Vec` if none cover it.

The structure is generic over the value type `T` (no trait bounds required). Values are owned by the
map; `get`/`get_all` return borrows.

Tests live in `tests/` and use `challenge::IntervalMap`.

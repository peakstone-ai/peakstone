# Group consecutive runs

Implement the library file **`src/lib.rs`** exposing:

```rust
pub fn group_consecutive<T: PartialEq + Clone>(items: &[T]) -> Vec<(T, usize)>
```

Collapse runs of consecutive equal elements (a form of run-length encoding).
Walk `items` left to right; each maximal run of equal adjacent elements becomes a
single `(value, run_length)` pair in the output. Pairs appear in the same order
the runs occur, and `run_length` is always at least `1`.

The function is **generic**: it must work for any element type `T` that is
`PartialEq + Clone` (e.g. `i32`, `char`, `String`). Use `PartialEq` to compare
adjacent elements and `Clone` to copy the representative value into the result.
Do not require `T: Copy`, `T: Hash`, or `T: Ord`.

Behavior:

- Empty input returns an empty `Vec`.
- Only **consecutive** equal elements are merged; equal elements separated by a
  different element form separate runs.

Examples:

- `group_consecutive(&[1, 1, 2, 3, 3, 3])` → `vec![(1, 2), (2, 1), (3, 3)]`
- `group_consecutive(&['a', 'a', 'b', 'a'])` → `vec![('a', 2), ('b', 1), ('a', 1)]`
- `group_consecutive::<i32>(&[])` → `vec![]`
- `group_consecutive(&[1, 2, 3])` → `vec![(1, 1), (2, 1), (3, 1)]`
- `group_consecutive(&[7, 7, 7])` → `vec![(7, 3)]`

Use only the standard library. Tests live in `tests/` and call it as
`challenge::group_consecutive`.

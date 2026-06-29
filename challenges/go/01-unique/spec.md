# Unique preserving order

Implement **`solution.go`** in `package challenge` exporting:

```go
func Unique(xs []int) []int
```

Return a new slice containing the elements of `xs` with duplicates removed, keeping each value at
the position of its **first occurrence**.

Rules:

- Preserve **first-occurrence order** — do not sort the result.
- Each distinct value appears exactly once.
- Do **not** mutate the input slice.
- For an empty (or nil) input, return an **empty, non-nil** slice (length 0).

Examples:

```go
Unique([]int{3, 1, 3, 2, 1}) // => [3, 1, 2]
Unique([]int{1, 2, 3})       // => [1, 2, 3]
Unique([]int{5, 5, 5})       // => [5]
Unique([]int{})              // => [] (non-nil, length 0)
```

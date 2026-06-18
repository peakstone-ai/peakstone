# Concurrent ordered map

Implement **`solution.go`** in `package challenge` exporting:

```go
func MapConcurrent(inputs []int, workers int, fn func(int) int) []int
```

Apply `fn` to every element of `inputs` using a pool of **at most `workers`**
goroutines running concurrently, and return the results.

Rules:

- The returned slice has the **same length** as `inputs`, and `result[i]` is
  `fn(inputs[i])` — i.e. results are in the **same order as the inputs**,
  regardless of the order goroutines finish in.
- Work must be distributed across concurrent goroutines (use goroutines plus
  channels and/or `sync.WaitGroup`). No more than `workers` goroutines may be
  processing elements at the same time.
- `workers` may be larger than `len(inputs)`; never start more workers than
  there is work for, and never start fewer than one when there is work.
- If `inputs` is empty (or `nil`), return an empty (non-nil is fine, but it must
  have length 0) slice without starting any work.
- You may assume `workers >= 1` and that `fn` is safe to call concurrently
  (it does not share mutable state).

Examples:

- `MapConcurrent([]int{1, 2, 3}, 2, func(x int) int { return x * x })` → `[]int{1, 4, 9}`
- `MapConcurrent([]int{}, 4, fn)` → `[]int{}`
- `MapConcurrent([]int{5}, 8, func(x int) int { return x + 1 })` → `[]int{6}`

# Generic LRU cache

Implement **`solution.go`** in `package challenge` exporting a generic
least-recently-used cache:

```go
type LRUCache[K comparable, V any] struct { /* unexported fields */ }

func NewLRUCache[K comparable, V any](capacity int) *LRUCache[K, V]

func (c *LRUCache[K, V]) Get(key K) (V, bool)
func (c *LRUCache[K, V]) Put(key K, value V)
func (c *LRUCache[K, V]) Len() int
```

Behavior:

- `NewLRUCache(capacity)` creates an empty cache that holds at most `capacity`
  entries. If `capacity <= 0`, treat it as `0`: the cache stores nothing and
  `Len()` is always `0`.
- `Get(key)` returns the stored value and `true` if `key` is present, or the
  zero value of `V` and `false` otherwise. A successful `Get` counts as a
  **use**, making `key` the most-recently-used entry.
- `Put(key, value)` inserts or updates `key`. Inserting or updating makes `key`
  the most-recently-used entry. If adding a **new** key would exceed `capacity`,
  the **least-recently-used** entry is evicted first. Updating the value of an
  existing key never evicts anything.
- `Len()` returns the current number of stored entries.
- Works for any `comparable` key type and any value type (e.g. `string`/`int`
  keys, struct or pointer values).

Examples:

```go
c := NewLRUCache[string, int](2)
c.Put("a", 1)
c.Put("b", 2)
c.Get("a")        // (1, true); now "b" is least-recently-used
c.Put("c", 3)     // evicts "b"
c.Get("b")        // (0, false)
c.Len()           // 2
```

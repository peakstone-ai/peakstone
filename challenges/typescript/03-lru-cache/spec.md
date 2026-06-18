# Generic LRU cache

Implement **`solution.ts`** exporting a generic class:

```ts
export class LRUCache<K, V> {
  constructor(capacity: number);
  get(key: K): V | undefined;
  put(key: K, value: V): void;
  get size(): number;
}
```

A least-recently-used cache holding at most `capacity` entries.

- `get(key)` returns the stored value, or `undefined` if absent. A successful `get`
  counts as a **use** (it makes that key the most-recently used).
- `put(key, value)` inserts or updates a key. Updating an existing key also counts as a
  use. When inserting a **new** key would exceed `capacity`, evict the
  least-recently-used key first.
- `size` is the current number of entries (never exceeds `capacity`).
- Throw a `RangeError` if `capacity < 1`.

Example:

```ts
const c = new LRUCache<string, number>(2);
c.put("a", 1);
c.put("b", 2);
c.get("a");      // 1  -> "a" is now most-recently used
c.put("c", 3);   // evicts "b" (least-recently used)
c.get("b");      // undefined
c.get("a");      // 1
c.get("c");      // 3
c.size;          // 2
```

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.

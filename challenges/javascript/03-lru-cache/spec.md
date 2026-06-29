# LRU cache

Implement an ES module **`solution.js`** exporting a least-recently-used cache class:

```js
export class LRUCache {
  constructor(capacity) { /* ... */ }
  get(key) { /* ... */ }
  put(key, value) { /* ... */ }
}
```

`capacity` is a positive integer — the maximum number of entries the cache holds.

- **`get(key)`** returns the stored value, or `undefined` if the key is not present. A successful
  `get` counts as a use: it marks the key as the **most recently used**.
- **`put(key, value)`** inserts or updates the entry and marks it most recently used. If adding a
  **new** key would exceed `capacity`, evict the **least recently used** entry first. Updating an
  existing key never changes the number of entries (and refreshes its recency).

"Recently used" is updated by **both** `get` and `put`. Keys may be any value usable as a `Map` key.

Example:
```js
const c = new LRUCache(2);
c.put("a", 1);
c.put("b", 2);
c.get("a");       // => 1   (now "a" is most-recently-used, "b" is least)
c.put("c", 3);    // capacity exceeded -> evicts "b"
c.get("b");       // => undefined
c.get("a");       // => 1
c.get("c");       // => 3
```

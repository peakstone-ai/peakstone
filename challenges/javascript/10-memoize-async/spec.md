# Async memoize with TTL and in-flight dedup

Implement an ES module **`solution.js`** (no external libraries):

```js
export function memoizeAsync(fn, { ttlMs, now = Date.now } = {}) { /* ... */ }
```

Return a memoized version of the async function `fn`. The cache key is
`JSON.stringify(args)` (the array of arguments the wrapper was called with).

Behavior:
- **Cache hit:** if a previous call with the same key resolved within the last `ttlMs`
  milliseconds, return the cached value **without calling `fn` again**.
- **In-flight dedup:** if a call with the same key is already pending (its promise has not
  settled yet), a new call with that key must return the **same in-flight promise** — `fn`
  is invoked only once for concurrent identical calls.
- **Expiry:** once a cached entry is older than `ttlMs`, the next call with that key calls
  `fn` again and refreshes the entry.
- Different keys are cached independently.

**Injectable clock:** time is read via the `now` option (a function returning the current
time in ms), which defaults to `Date.now`. Tests pass a controllable `now` so expiry is
deterministic. Timestamp a cache entry using `now()` when it resolves (or when the call
starts — either is acceptable as long as expiry is measured against `now()`).

If a pending call rejects, the entry must not be cached (the next call retries).

Example:
```js
let calls = 0;
let t = 1000;
const slow = async (x) => { calls++; return x * 2; };
const m = memoizeAsync(slow, { ttlMs: 100, now: () => t });

await Promise.all([m(5), m(5)]); // calls === 1 (deduped)
await m(5);                      // calls === 1 (cache hit)
t += 200;                        // advance past ttl
await m(5);                      // calls === 2 (expired)
```

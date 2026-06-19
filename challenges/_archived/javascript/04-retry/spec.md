# Async retry with exponential backoff

Implement an ES module **`solution.js`** that exports an async function:

```js
export async function retry(fn, { retries = 3, baseDelayMs = 10 } = {}) { /* ... */ }
```

`fn` is an async function (or any function returning a promise). `retry` calls
`fn()` and:

- If it resolves, `retry` resolves with that value.
- If it rejects, `retry` retries, up to `retries` additional attempts (so `fn` is
  called at most `retries + 1` times total).
- Between attempts it waits with **exponential backoff**: before the retry for a
  given `attempt` (0-based; the first retry is `attempt = 0`), wait
  `baseDelayMs * 2 ** attempt` milliseconds.
- If all attempts are exhausted, `retry` rejects with the **last** error thrown.

Behavior:
- `retries = 0` means `fn` is called exactly once (no retries).
- A successful call short-circuits remaining retries.

Examples:
- `fn` that fails twice then succeeds, with `retries = 3` → resolves with the
  success value; `fn` was called 3 times.
- `fn` that always rejects, with `retries = 2` → rejects with the last error;
  `fn` was called 3 times.

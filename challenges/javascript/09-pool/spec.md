# Concurrency-limited async pool

Implement an ES module **`solution.js`** (no external libraries):

```js
export async function pool(thunks, concurrency) { /* ... */ }
```

`thunks` is an array of zero-argument functions, each returning a promise (async thunks).
Run them with **at most `concurrency` running at the same time**, and resolve with an array
of their results **in the original order of `thunks`** (not completion order).

Requirements:
- The result at index `i` must be the resolved value of `thunks[i]`.
- At no point may more than `concurrency` thunks be in flight simultaneously.
- As soon as one thunk settles, the next pending thunk should start (keep the pool full).
- An empty `thunks` array resolves to `[]`.
- You may assume `concurrency >= 1`.

Notes:
- Do not simply run everything via `Promise.all(thunks.map(...))` — that ignores the limit.
- You do not need to handle rejections specially (a rejecting thunk may reject the pool).

Example:
```js
const order = [];
const make = (id, ms) => () =>
  new Promise((res) => setTimeout(() => { order.push(id); res(id); }, ms));
await pool([make("a", 30), make("b", 10), make("c", 20)], 2);
// => ["a", "b", "c"]  (results in original order, regardless of finish order)
```

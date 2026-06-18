# Typed Result type

Implement **`solution.ts`** exporting a generic, discriminated-union `Result` type and
helpers for working with it (a small Rust-style `Result`).

Export exactly these, with these signatures:

```ts
export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

export function ok<T>(v: T): Result<T, never>;
export function err<E>(e: E): Result<never, E>;
export function map<T, U, E>(r: Result<T, E>, f: (t: T) => U): Result<U, E>;
export function unwrapOr<T, E>(r: Result<T, E>, fallback: T): T;
```

Behavior:

- `ok(v)` returns `{ ok: true, value: v }`.
- `err(e)` returns `{ ok: false, error: e }`.
- `map(r, f)`:
  - if `r.ok` is `true`, returns `ok(f(r.value))` (apply `f` to the value);
  - otherwise returns `r` unchanged (the error is propagated, `f` is **not** called).
- `unwrapOr(r, fallback)`:
  - returns `r.value` when `r.ok` is `true`, otherwise returns `fallback`.

The return types must be exactly as written above. The discriminant `ok` must narrow the
union (so that inside an `if (r.ok)` branch `r.value` is available and in the `else`
branch `r.error` is available). `ok`'s error type is `never` and `err`'s value type is
`never` so they compose with any `Result`.

Example:
```ts
const r = map(ok(2), (n) => n + 1);   // Result<number, never>, { ok: true, value: 3 }
unwrapOr(r, 0);                        // 3
unwrapOr(err("boom"), 42);            // 42
```

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.

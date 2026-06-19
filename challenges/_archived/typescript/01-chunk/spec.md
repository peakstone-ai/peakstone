# Generic array `chunk`

Implement **`solution.ts`** exporting a generic function:

```ts
export function chunk<T>(arr: T[], size: number): T[][] { /* ... */ }
```

Split `arr` into consecutive sub-arrays of length `size` (the last chunk may be shorter).

- `chunk([1,2,3,4,5], 2)` → `[[1,2],[3,4],[5]]`
- `chunk([], 3)` → `[]`
- Throw a `RangeError` if `size < 1`.

Keep it fully typed (must pass `tsc --noEmit` in strict mode).

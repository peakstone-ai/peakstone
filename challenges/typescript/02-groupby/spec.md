# Generic `groupBy`

Implement **`solution.ts`** exporting a generic function:

```ts
export function groupBy<T, K extends string | number>(
  items: T[],
  keyFn: (item: T) => K,
): Record<K, T[]>
```

Group the `items` into a record keyed by the result of `keyFn(item)`. Each value is
the array of items that produced that key, **in their original order**.

- `groupBy([1, 2, 3, 4], (n) => (n % 2 === 0 ? "even" : "odd"))`
  → `{ odd: [1, 3], even: [2, 4] }`
- `groupBy([], (n: number) => n)` → `{}`
- A numeric key works too:
  `groupBy(["a", "bb", "ccc", "dd"], (s) => s.length)`
  → `{ 1: ["a"], 2: ["bb", "dd"], 3: ["ccc"] }`

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.

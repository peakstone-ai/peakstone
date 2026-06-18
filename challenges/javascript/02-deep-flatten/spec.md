# Deep flatten

Implement an ES module **`solution.js`** that exports a function:

```js
export function flatten(arr) { /* ... */ }
```

It deep-flattens an arbitrarily nested array into a single-level array, preserving
the left-to-right order of the leaf elements. Non-array values are kept as-is.
Empty arrays contribute nothing to the output.

The input array is not mutated.

Examples:
- `flatten([1, [2, [3, [4]], 5]])` → `[1, 2, 3, 4, 5]`
- `flatten([])` → `[]`
- `flatten([[], [1], [], [2, [3]]])` → `[1, 2, 3]`
- `flatten([1, 2, 3])` → `[1, 2, 3]`

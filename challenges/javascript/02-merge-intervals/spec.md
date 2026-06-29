# Merge overlapping intervals

Implement an ES module **`solution.js`** exporting a single function:

```js
export function mergeIntervals(intervals) { /* ... */ }
```

`intervals` is an array of `[start, end]` pairs of numbers, each a **closed** interval with
`start <= end`. Merge all overlapping intervals and return a new array of merged intervals
**sorted ascending by start**.

Rules:
- Intervals that **touch** are merged: `[1, 3]` and `[3, 5]` become `[1, 5]`.
- A merged interval's end is the **maximum** end of the intervals that went into it (handle full
  containment, e.g. `[1, 10]` swallows `[2, 3]`).
- The input may be in any order and may contain duplicates. Do **not** mutate the input array.
- An empty input returns `[]`.

Examples:
```js
mergeIntervals([[1, 4], [2, 5]])            // => [[1, 5]]
mergeIntervals([[3, 5], [1, 2]])            // => [[1, 2], [3, 5]]
mergeIntervals([[1, 3], [3, 5]])            // => [[1, 5]]
mergeIntervals([[1, 10], [2, 3], [4, 8]])   // => [[1, 10]]
mergeIntervals([])                          // => []
```

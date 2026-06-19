# Search insert position

Implement an ES module **`solution.js`** that exports a function:

```js
export function searchInsert(sortedNums, target) { /* ... */ }
```

`sortedNums` is an array of numbers sorted in ascending order. Return the index of
`target` if it is present. If it is not present, return the index where it would be
inserted to keep the array sorted.

Your solution **must run in O(log n) time** (use binary search).

If the array contains duplicates of `target`, returning the index of any matching
occurrence is acceptable.

Examples:
- `searchInsert([1, 3, 5, 6], 5)` → `2`
- `searchInsert([1, 3, 5, 6], 2)` → `1`
- `searchInsert([1, 3, 5, 6], 7)` → `4`
- `searchInsert([1, 3, 5, 6], 0)` → `0`
- `searchInsert([], 1)` → `0`

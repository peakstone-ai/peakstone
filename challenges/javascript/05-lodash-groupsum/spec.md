# Group-and-sum (lodash)

Implement an ES module **`solution.js`** that uses **lodash** (already installed — import it):

```js
import _ from "lodash";

export function groupSum(items, groupKey, valueKey) { /* ... */ }
```

Group `items` (an array of objects) by the value of `groupKey`, summing `valueKey` within
each group. Return a plain object mapping each group value to its numeric sum.

Example:
```js
groupSum([
  { dept: "eng", cost: 100 },
  { dept: "eng", cost: 50 },
  { dept: "sales", cost: 70 },
], "dept", "cost")
// => { eng: 150, sales: 70 }
```
An empty array returns `{}`. You are expected to use lodash helpers (e.g. `_.groupBy`,
`_.sumBy`, `_.mapValues`).

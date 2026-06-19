# Evaluate expression over scopes (mathjs)

Implement an ES module **`solution.js`** that uses **mathjs** (already installed — import it):

```js
import { compile } from "mathjs";

export function evaluateAll(expr, scopes) { /* ... */ }
```

Given a math expression string `expr` and an array `scopes` of plain objects (each a set
of variable bindings), evaluate `expr` once per scope and return an **array of numeric
results** in the same order as `scopes`.

- Use mathjs so that the expression is parsed once and reused (e.g. `compile(expr)` then
  `node.evaluate(scope)` for each scope). Plain `evaluate(expr, scope)` per scope is also
  acceptable.
- The expression may reference variables (e.g. `a`, `b`), built-in functions
  (e.g. `sqrt`, `max`), and constants (e.g. `pi`).
- An empty `scopes` array returns `[]`.

Examples:
```js
evaluateAll("a + b", [{ a: 1, b: 2 }, { a: 10, b: 20 }]) // => [3, 30]
evaluateAll("sqrt(x^2 + y^2)", [{ x: 3, y: 4 }])         // => [5]
evaluateAll("2 * pi", [{}])                              // => [6.283185307179586]
```

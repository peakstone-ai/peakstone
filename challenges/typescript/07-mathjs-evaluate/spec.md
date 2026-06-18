# Compile and evaluate expressions (mathjs)

Implement **`solution.ts`** using **mathjs** (already installed — import what you need,
e.g. `import { compile } from "mathjs";`).

Export exactly one function:

```ts
export function evaluateAll(expr: string, scopes: Record<string, number>[]): number[];
```

Behavior:

- **Compile the expression once** with mathjs (`compile(expr)`), then evaluate the
  compiled expression against **each** scope in `scopes`, in order.
- Return an array of the numeric results (one per scope). Convert each result to a
  `number` so the return type is exactly `number[]`.
- An empty `scopes` array returns `[]`.

The expression may reference variables supplied by the scope and may use mathjs built-in
functions (e.g. `sqrt`, `max`, `sin`).

Examples:
```ts
evaluateAll("a^2 + b", [{ a: 3, b: 1 }, { a: 2, b: 5 }]);
// => [10, 9]

evaluateAll("sqrt(x) + max(y, 1)", [{ x: 9, y: 4 }]);
// => [7]   // sqrt(9)=3, max(4,1)=4

evaluateAll("a + b", []);
// => []
```

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.

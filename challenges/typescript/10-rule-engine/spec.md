# Typed rule / query engine

Implement a file **`solution.ts`** that interprets a small, tree-shaped rule language
over plain records and uses it to filter collections of records.

## Types to export

```ts
export type Rule =
  | { op: "and"; rules: Rule[] }
  | { op: "or"; rules: Rule[] }
  | { op: "not"; rule: Rule }
  | { op: "eq" | "ne" | "lt" | "lte" | "gt" | "gte"; field: string; value: number | string }
  | { op: "in"; field: string; values: Array<number | string> };

export class RuleError extends Error {}

export function evaluate(rule: Rule, record: Record<string, unknown>): boolean;

export function filter(
  rule: Rule,
  records: Array<Record<string, unknown>>,
): Array<Record<string, unknown>>;
```

## Semantics

`evaluate(rule, record)` returns a boolean by recursively interpreting `rule` against a
single `record`.

### Logical combinators

- `and`: true iff **every** sub-rule in `rules` is true. An empty `rules` array is
  **true** (the identity of conjunction).
- `or`: true iff **any** sub-rule in `rules` is true. An empty `rules` array is
  **false** (the identity of disjunction).
- `not`: the negation of its single child `rule`.

### Comparisons

Comparison ops look up `record[field]`. Let `fieldValue = record[field]`.

- `eq`: true iff `fieldValue === value`.
- `ne`: true iff `fieldValue !== value`.
- `lt` / `lte` / `gt` / `gte`: ordering comparisons. They are evaluated **only** when
  `fieldValue` and `value` have the same comparable type:
  - if **both** are numbers, compare numerically;
  - if **both** are strings, compare lexicographically (with `<`, `<=`, `>`, `>=`);
  - otherwise (the field is missing/`undefined`, or one side is a number and the other
    a string, or the field holds some other type) the comparison is **`false`**. It does
    **not** throw.

So `{ op: "gt", field: "age", value: 18 }` is `false` for a record with no `age`, and
also `false` if `age` is the string `"20"` (string vs number mismatch).

### Membership

- `in`: true iff `record[field]` is **strictly equal** (`===`) to at least one element
  of `values`.

### Validation — when to throw `RuleError`

A rule node is invalid if it is not a well-formed member of the `Rule` union. Invalid
nodes must cause `evaluate` (and therefore `filter`) to throw a `RuleError` (not a plain
`Error`). In particular, throw `RuleError` when:

- `op` is missing or is not one of the known operators;
- `and` / `or` does not carry an array `rules`;
- `not` does not carry a child `rule` object;
- a comparison op (`eq`/`ne`/`lt`/`lte`/`gt`/`gte`) does not carry a string `field`, or
  its `value` is neither a number nor a string;
- `in` does not carry a string `field` or an array `values`.

You may validate up front or lazily as you evaluate; either is fine, as long as invalid
rules raise `RuleError`.

## `filter`

`filter(rule, records)` returns a new array containing exactly the records for which
`evaluate(rule, record)` is `true`, **in their original order**. If `rule` is invalid it
propagates the `RuleError`.

## Worked example

```ts
const rule: Rule = {
  op: "and",
  rules: [
    { op: "gte", field: "age", value: 18 },
    {
      op: "or",
      rules: [
        { op: "eq", field: "country", value: "US" },
        { op: "in", field: "country", values: ["CA", "MX"] },
      ],
    },
    { op: "not", rule: { op: "eq", field: "banned", value: 1 } },
  ],
};

const people = [
  { name: "a", age: 25, country: "US", banned: 0 }, // kept
  { name: "b", age: 17, country: "US", banned: 0 }, // dropped: age < 18
  { name: "c", age: 40, country: "CA", banned: 1 }, // dropped: banned
  { name: "d", age: 30, country: "FR", banned: 0 }, // dropped: country
  { name: "e", age: 22, country: "MX", banned: 0 }, // kept
];

filter(rule, people); // -> [ {name:"a",...}, {name:"e",...} ]
```

Keep it fully typed: `solution.ts` must pass `tsc --noEmit` in strict mode. Do not use
`any` in the implementation; prefer `unknown` and narrow.

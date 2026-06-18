# In-memory SQL SELECT engine

Implement a file **`solution.ts`** that parses a small `SELECT` statement and executes
it against an in-memory table of rows. This is a parser + interpreter exercise: you must
tokenize the query, build a small AST, validate it, and evaluate it over the data.

## Types to export

```ts
export type Row = Record<string, number | string>;

export class QueryError extends Error {}

// Parse and execute a small SQL SELECT against the given rows. Returns the result rows.
export function query(sql: string, rows: Row[]): Row[];
```

The `rows` argument **is** the table; the table name in the query is accepted but
otherwise ignored (the data comes from `rows` regardless of the name written).

## Grammar

```
SELECT <cols> FROM <table> [WHERE <cond>] [ORDER BY <col> [ASC|DESC]] [LIMIT <n>]
```

The clauses, when present, must appear in exactly this order. The four optional clauses
(`WHERE`, `ORDER BY`, `LIMIT`) are each optional and independent.

### `<cols>`

- `*` selects **all** columns. Each result row preserves that source row's own key
  insertion order (rows are copied; no column is renamed or reordered).
- Otherwise a comma-separated list of column names, e.g. `name, age`. The result rows
  then contain **exactly** those columns, **in the listed order**. A selected column that
  is missing from a given source row is simply omitted from that row's output (it is not
  an error, and no placeholder value is inserted).

### `<table>`

A bare identifier (letters, digits, `_`, not starting with a digit). Any name is accepted.

### `<cond>` (the `WHERE` clause)

One or more comparisons combined with `AND` / `OR`. There are **no parentheses**.
`AND` binds **tighter** than `OR`, so

```
a = 1 AND b = 2 OR c = 3
```

parses as `(a = 1 AND b = 2) OR (c = 3)`.

A single comparison is `col <op> value` where:

- `<op>` is one of `=  !=  <  >  <=  >=`.
- `value` is either an **integer literal** (optionally signed, e.g. `42`, `-3`, `0`) or a
  **single-quoted string** (e.g. `'alice'`). Strings may contain spaces; an unterminated
  string literal is an error.

Comparison semantics, given `cell = row[col]`:

- `=` / `!=` work for both numbers and strings using strict (in)equality. If `cell` is a
  number and `value` is a string (or vice versa), they are considered **not equal** (so
  `=` is `false`, `!=` is `true`).
- `<  >  <=  >=` are ordering comparisons:
  - both number  -> numeric comparison;
  - both string  -> lexicographic comparison (JavaScript `<`/`>` on strings);
  - **type mismatch** (one number, one string) -> the comparison is **`false`**.
- If `col` is **not present** in the row, the comparison is treated as a non-match:
  `=` is `false`, `!=` is `true`, and every ordering comparison is `false`. This does
  **not** throw — only *syntactically* invalid queries throw.

A row is included iff the whole `<cond>` evaluates to true for it. With no `WHERE`, all
rows match.

### `ORDER BY <col> [ASC|DESC]`

Sort the result by a single column. `ASC` (the default) sorts ascending; `DESC`
descending. Numbers sort numerically, strings lexicographically. The sort must be
**stable**: rows that compare equal keep their relative input order. A mismatched-type or
missing sort key compares as equal to the others (it does not throw and does not crash);
ties are broken by stability (original order).

### `LIMIT <n>`

Keep the first `n` result rows after ordering. `n` must be a **non-negative integer**.

### Case sensitivity

Keywords (`SELECT`, `FROM`, `WHERE`, `AND`, `OR`, `ORDER`, `BY`, `ASC`, `DESC`, `LIMIT`)
are **case-insensitive** — `select` and `SELECT` are equivalent. Column names and quoted
string values are **case-sensitive**.

## Evaluation order

`WHERE` filtering -> `ORDER BY` sorting -> `LIMIT` truncation -> column projection.
(Projection last means you may order by a column you did not select.)

## Errors — throw `QueryError`

Throw a `QueryError` (not a plain `Error`) for any **syntactically invalid** query,
including:

- a statement that does not start with `SELECT`, or has no `FROM`;
- an empty column list, or a trailing/embedded comma in the column list;
- an unknown clause / leftover tokens after a valid statement;
- a bad comparison operator, or a comparison missing its column / operator / value;
- an unterminated single-quoted string;
- a `LIMIT` whose argument is missing or is not a non-negative integer;
- an `ORDER BY` without a column.

Referencing a column that is absent from a particular row at **evaluation** time (in
`WHERE` or `ORDER BY`) is **not** an error — see the semantics above.

## Worked example

```ts
const rows: Row[] = [
  { id: 1, name: "alice", age: 30 },
  { id: 2, name: "bob", age: 25 },
  { id: 3, name: "carol", age: 30 },
  { id: 4, name: "dave", age: 17 },
];

query(
  "SELECT name, age FROM users WHERE age >= 18 ORDER BY age DESC LIMIT 2",
  rows,
);
// WHERE drops dave (17). Remaining: alice(30), bob(25), carol(30).
// ORDER BY age DESC (stable): alice(30), carol(30), bob(25).
// LIMIT 2:                    alice(30), carol(30).
// Projection name, age:
// -> [ { name: "alice", age: 30 }, { name: "carol", age: 30 } ]
```

Keep it fully typed: `solution.ts` must pass `tsc --noEmit` in strict mode. Do not use
`any` in the implementation; prefer `unknown` and narrow.

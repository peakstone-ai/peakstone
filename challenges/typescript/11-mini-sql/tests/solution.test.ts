import { test } from "node:test";
import { strict as assert } from "node:assert";
import { query, QueryError, type Row } from "./solution.ts";

function people(): Row[] {
  return [
    { id: 1, name: "alice", age: 30, city: "NYC" },
    { id: 2, name: "bob", age: 25, city: "LA" },
    { id: 3, name: "carol", age: 30, city: "NYC" },
    { id: 4, name: "dave", age: 17, city: "SF" },
  ];
}

test("SELECT * preserves all columns and per-row key order", () => {
  const rows: Row[] = [{ z: 1, a: "x", m: 2 }];
  const out = query("SELECT * FROM t", rows);
  assert.deepEqual(out, [{ z: 1, a: "x", m: 2 }]);
  assert.deepEqual(Object.keys(out[0]!), ["z", "a", "m"]);
  // Result is a copy, not the same object.
  assert.notEqual(out[0], rows[0]);
});

test("explicit column list selects exactly those columns in order", () => {
  const out = query("SELECT name, id FROM users", people());
  assert.deepEqual(out, [
    { name: "alice", id: 1 },
    { name: "bob", id: 2 },
    { name: "carol", id: 3 },
    { name: "dave", id: 4 },
  ]);
  assert.deepEqual(Object.keys(out[0]!), ["name", "id"]);
});

test("selected column missing from a row is omitted, not an error", () => {
  const rows: Row[] = [{ a: 1, b: 2 }, { a: 3 }];
  const out = query("SELECT a, b FROM t", rows);
  assert.deepEqual(out, [{ a: 1, b: 2 }, { a: 3 }]);
});

test("WHERE = and != on numbers", () => {
  assert.deepEqual(
    query("SELECT name FROM u WHERE age = 30", people()),
    [{ name: "alice" }, { name: "carol" }],
  );
  assert.deepEqual(
    query("SELECT name FROM u WHERE age != 30", people()),
    [{ name: "bob" }, { name: "dave" }],
  );
});

test("WHERE = and != on strings (case-sensitive values)", () => {
  assert.deepEqual(
    query("SELECT name FROM u WHERE city = 'NYC'", people()),
    [{ name: "alice" }, { name: "carol" }],
  );
  // Wrong case does not match.
  assert.deepEqual(query("SELECT name FROM u WHERE city = 'nyc'", people()), []);
  assert.deepEqual(
    query("SELECT name FROM u WHERE name != 'alice'", people()).length,
    3,
  );
});

test("numeric ordering comparisons < > <= >=", () => {
  assert.deepEqual(
    query("SELECT name FROM u WHERE age < 30", people()),
    [{ name: "bob" }, { name: "dave" }],
  );
  assert.deepEqual(
    query("SELECT name FROM u WHERE age > 25", people()),
    [{ name: "alice" }, { name: "carol" }],
  );
  assert.deepEqual(
    query("SELECT name FROM u WHERE age <= 25", people()),
    [{ name: "bob" }, { name: "dave" }],
  );
  assert.deepEqual(
    query("SELECT name FROM u WHERE age >= 30", people()),
    [{ name: "alice" }, { name: "carol" }],
  );
});

test("lexicographic string ordering comparisons", () => {
  assert.deepEqual(
    query("SELECT name FROM u WHERE name < 'carol'", people()),
    [{ name: "alice" }, { name: "bob" }],
  );
  assert.deepEqual(
    query("SELECT name FROM u WHERE name >= 'carol'", people()),
    [{ name: "carol" }, { name: "dave" }],
  );
});

test("negative integer literals", () => {
  const rows: Row[] = [{ t: -5 }, { t: 0 }, { t: 3 }];
  assert.deepEqual(query("SELECT t FROM r WHERE t < 0", rows), [{ t: -5 }]);
  assert.deepEqual(query("SELECT t FROM r WHERE t = -5", rows), [{ t: -5 }]);
  assert.deepEqual(query("SELECT t FROM r WHERE t >= -5", rows), [
    { t: -5 },
    { t: 0 },
    { t: 3 },
  ]);
});

test("AND binds tighter than OR", () => {
  const rows: Row[] = [
    { a: 1, b: 2, c: 9 }, // a=1 AND b=2 -> true
    { a: 1, b: 5, c: 3 }, // c=3 -> true via OR
    { a: 9, b: 9, c: 9 }, // none -> false
  ];
  // (a = 1 AND b = 2) OR (c = 3)
  const out = query("SELECT a FROM t WHERE a = 1 AND b = 2 OR c = 3", rows);
  assert.deepEqual(out, [{ a: 1 }, { a: 1 }]);
});

test("OR then AND precedence: a = 1 OR a = 2 AND b = 9", () => {
  const rows: Row[] = [
    { a: 1, b: 0 }, // a=1 -> true
    { a: 2, b: 9 }, // a=2 AND b=9 -> true
    { a: 2, b: 0 }, // a=2 but b!=9 -> false
  ];
  // parses as a = 1 OR (a = 2 AND b = 9)
  const out = query("SELECT a, b FROM t WHERE a = 1 OR a = 2 AND b = 9", rows);
  assert.deepEqual(out, [{ a: 1, b: 0 }, { a: 2, b: 9 }]);
});

test("ORDER BY ascending (default) and DESC", () => {
  const asc = query("SELECT name FROM u ORDER BY age", people());
  assert.deepEqual(asc.map((r) => r["name"]), ["dave", "bob", "alice", "carol"]);
  const desc = query("SELECT name FROM u ORDER BY age DESC", people());
  assert.deepEqual(desc.map((r) => r["name"]), ["alice", "carol", "bob", "dave"]);
});

test("ORDER BY is stable for equal keys", () => {
  // alice and carol both have age 30; original order alice before carol.
  const asc = query("SELECT name FROM u ORDER BY age ASC", people());
  const names = asc.map((r) => r["name"]);
  assert.ok(names.indexOf("alice") < names.indexOf("carol"));
  const desc = query("SELECT name FROM u ORDER BY age DESC", people());
  const dnames = desc.map((r) => r["name"]);
  // Stability preserved under DESC too: equal keys keep input order.
  assert.ok(dnames.indexOf("alice") < dnames.indexOf("carol"));
});

test("ORDER BY a column not in the SELECT list, plus LIMIT", () => {
  const out = query(
    "SELECT name FROM u WHERE age >= 18 ORDER BY age DESC LIMIT 2",
    people(),
  );
  assert.deepEqual(out, [{ name: "alice" }, { name: "carol" }]);
});

test("LIMIT keeps first n and LIMIT 0 yields empty", () => {
  assert.deepEqual(
    query("SELECT id FROM u ORDER BY id LIMIT 2", people()),
    [{ id: 1 }, { id: 2 }],
  );
  assert.deepEqual(query("SELECT id FROM u LIMIT 0", people()), []);
  // LIMIT larger than result is fine.
  assert.deepEqual(query("SELECT id FROM u ORDER BY id LIMIT 99", people()).length, 4);
});

test("type-mismatch comparisons: = is false, != is true, ordering is false", () => {
  const rows: Row[] = [{ v: 5 }, { v: "5" }];
  // number cell vs string literal
  assert.deepEqual(query("SELECT v FROM t WHERE v = '5'", rows), [{ v: "5" }]);
  assert.deepEqual(query("SELECT v FROM t WHERE v != '5'", rows), [{ v: 5 }]);
  // ordering of number cell vs string literal is a type mismatch -> false,
  // but the string cell "5" vs string literal '9' is a valid string comparison.
  assert.deepEqual(query("SELECT v FROM t WHERE v < '9'", rows), [{ v: "5" }]);
  // numeric cell 5 vs string '9' is a mismatch (false); string cell "5" vs number 0 too.
  assert.deepEqual(query("SELECT v FROM t WHERE v > 0", rows), [{ v: 5 }]);
});

test("missing column in WHERE: = false, != true, ordering false (no throw)", () => {
  const rows: Row[] = [{ a: 1 }, { a: 2 }];
  assert.deepEqual(query("SELECT a FROM t WHERE missing = 1", rows), []);
  assert.deepEqual(query("SELECT a FROM t WHERE missing != 1", rows), [{ a: 1 }, { a: 2 }]);
  assert.deepEqual(query("SELECT a FROM t WHERE missing > 0", rows), []);
});

test("ORDER BY with missing / mismatched keys does not throw", () => {
  const rows: Row[] = [{ a: 2 }, { b: 1 }, { a: 1 }];
  // Rows without `a` compare as equal; should not throw.
  const out = query("SELECT * FROM t ORDER BY a", rows);
  assert.equal(out.length, 3);
});

test("keywords are case-insensitive; identifiers/strings are not", () => {
  const out = query(
    "select Name from u WHERE City = 'NYC' order by Age desc limit 1",
    people().map((r) => ({ Name: String(r["name"]), City: String(r["city"]), Age: Number(r["age"]) })),
  );
  assert.deepEqual(out, [{ Name: "alice" }]);
  // Mixed-case keywords work too.
  assert.deepEqual(
    query("SeLeCt id FrOm u Where age = 25", people()),
    [{ id: 2 }],
  );
});

test("no WHERE returns all rows; whitespace is tolerated", () => {
  assert.equal(query("  SELECT   *   FROM   t  ", people()).length, 4);
});

test("throws: missing SELECT", () => {
  assert.throws(() => query("FROM t", []), QueryError);
});

test("throws: missing FROM", () => {
  assert.throws(() => query("SELECT *", []), QueryError);
  assert.throws(() => query("SELECT a, b", []), QueryError);
});

test("throws: empty / malformed column list", () => {
  assert.throws(() => query("SELECT FROM t", []), QueryError);
  assert.throws(() => query("SELECT a, FROM t", []), QueryError);
  assert.throws(() => query("SELECT , a FROM t", []), QueryError);
});

test("throws: bad operator and malformed comparison", () => {
  assert.throws(() => query("SELECT * FROM t WHERE a == 1", []), QueryError);
  assert.throws(() => query("SELECT * FROM t WHERE a 1", []), QueryError);
  assert.throws(() => query("SELECT * FROM t WHERE a =", []), QueryError);
  assert.throws(() => query("SELECT * FROM t WHERE = 1", []), QueryError);
});

test("throws: unterminated string literal", () => {
  assert.throws(() => query("SELECT * FROM t WHERE name = 'alice", []), QueryError);
});

test("throws: bad LIMIT (missing, negative, non-integer, string)", () => {
  assert.throws(() => query("SELECT * FROM t LIMIT", []), QueryError);
  assert.throws(() => query("SELECT * FROM t LIMIT -1", []), QueryError);
  assert.throws(() => query("SELECT * FROM t LIMIT 'x'", []), QueryError);
});

test("throws: unknown clause / leftover tokens", () => {
  assert.throws(() => query("SELECT * FROM t GROUP BY a", []), QueryError);
  assert.throws(() => query("SELECT * FROM t WHERE a = 1 b = 2", []), QueryError);
  assert.throws(() => query("SELECT * FROM t ORDER BY", []), QueryError);
});

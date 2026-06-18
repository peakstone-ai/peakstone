import { test } from "node:test";
import { strict as assert } from "node:assert";
import { evaluate, filter, RuleError, type Rule } from "./solution.ts";

test("eq / ne on numbers and strings", () => {
  assert.equal(evaluate({ op: "eq", field: "a", value: 1 }, { a: 1 }), true);
  assert.equal(evaluate({ op: "eq", field: "a", value: 1 }, { a: 2 }), false);
  assert.equal(evaluate({ op: "ne", field: "a", value: 1 }, { a: 2 }), true);
  assert.equal(evaluate({ op: "eq", field: "s", value: "x" }, { s: "x" }), true);
  assert.equal(evaluate({ op: "ne", field: "s", value: "x" }, { s: "y" }), true);
});

test("eq does not coerce types (number vs string)", () => {
  assert.equal(evaluate({ op: "eq", field: "a", value: 1 }, { a: "1" }), false);
  assert.equal(evaluate({ op: "ne", field: "a", value: 1 }, { a: "1" }), true);
});

test("numeric lt / lte / gt / gte", () => {
  assert.equal(evaluate({ op: "lt", field: "n", value: 10 }, { n: 5 }), true);
  assert.equal(evaluate({ op: "lt", field: "n", value: 10 }, { n: 10 }), false);
  assert.equal(evaluate({ op: "lte", field: "n", value: 10 }, { n: 10 }), true);
  assert.equal(evaluate({ op: "gt", field: "n", value: 10 }, { n: 11 }), true);
  assert.equal(evaluate({ op: "gt", field: "n", value: 10 }, { n: 10 }), false);
  assert.equal(evaluate({ op: "gte", field: "n", value: 10 }, { n: 10 }), true);
});

test("lexicographic string ordering", () => {
  assert.equal(evaluate({ op: "lt", field: "s", value: "banana" }, { s: "apple" }), true);
  assert.equal(evaluate({ op: "gt", field: "s", value: "apple" }, { s: "banana" }), true);
  assert.equal(evaluate({ op: "gte", field: "s", value: "apple" }, { s: "apple" }), true);
  assert.equal(evaluate({ op: "lte", field: "s", value: "apple" }, { s: "apple" }), true);
});

test("ordering with missing field is false", () => {
  assert.equal(evaluate({ op: "gt", field: "age", value: 18 }, {}), false);
  assert.equal(evaluate({ op: "lt", field: "age", value: 18 }, {}), false);
  assert.equal(evaluate({ op: "lte", field: "age", value: 18 }, {}), false);
  assert.equal(evaluate({ op: "gte", field: "age", value: 18 }, {}), false);
});

test("ordering with type mismatch is false (no throw)", () => {
  // number value, string field
  assert.equal(evaluate({ op: "gt", field: "age", value: 18 }, { age: "20" }), false);
  // string value, number field
  assert.equal(evaluate({ op: "lt", field: "age", value: "20" }, { age: 18 }), false);
  // field holds a non-comparable type
  assert.equal(evaluate({ op: "gt", field: "age", value: 1 }, { age: true }), false);
});

test("eq with missing field is false, ne is true", () => {
  assert.equal(evaluate({ op: "eq", field: "x", value: 1 }, {}), false);
  assert.equal(evaluate({ op: "ne", field: "x", value: 1 }, {}), true);
});

test("in membership", () => {
  assert.equal(evaluate({ op: "in", field: "c", values: ["US", "CA"] }, { c: "CA" }), true);
  assert.equal(evaluate({ op: "in", field: "c", values: ["US", "CA"] }, { c: "FR" }), false);
  assert.equal(evaluate({ op: "in", field: "n", values: [1, 2, 3] }, { n: 2 }), true);
  // strict equality: "1" is not 1
  assert.equal(evaluate({ op: "in", field: "n", values: [1, 2, 3] }, { n: "1" }), false);
  // empty values -> never matches
  assert.equal(evaluate({ op: "in", field: "n", values: [] }, { n: 1 }), false);
});

test("not negates its child", () => {
  assert.equal(evaluate({ op: "not", rule: { op: "eq", field: "a", value: 1 } }, { a: 1 }), false);
  assert.equal(evaluate({ op: "not", rule: { op: "eq", field: "a", value: 1 } }, { a: 2 }), true);
});

test("empty and is true, empty or is false", () => {
  assert.equal(evaluate({ op: "and", rules: [] }, {}), true);
  assert.equal(evaluate({ op: "or", rules: [] }, {}), false);
});

test("and / or short-circuit semantics over multiple rules", () => {
  const r: Rule = {
    op: "and",
    rules: [
      { op: "gte", field: "age", value: 18 },
      { op: "eq", field: "country", value: "US" },
    ],
  };
  assert.equal(evaluate(r, { age: 20, country: "US" }), true);
  assert.equal(evaluate(r, { age: 17, country: "US" }), false);
  assert.equal(evaluate(r, { age: 20, country: "FR" }), false);

  const o: Rule = {
    op: "or",
    rules: [
      { op: "eq", field: "country", value: "US" },
      { op: "eq", field: "country", value: "CA" },
    ],
  };
  assert.equal(evaluate(o, { country: "CA" }), true);
  assert.equal(evaluate(o, { country: "FR" }), false);
});

test("deeply nested and / or / not", () => {
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
  assert.equal(evaluate(rule, { age: 25, country: "US", banned: 0 }), true);
  assert.equal(evaluate(rule, { age: 17, country: "US", banned: 0 }), false);
  assert.equal(evaluate(rule, { age: 40, country: "CA", banned: 1 }), false);
  assert.equal(evaluate(rule, { age: 30, country: "FR", banned: 0 }), false);
  assert.equal(evaluate(rule, { age: 22, country: "MX", banned: 0 }), true);
});

test("filter keeps matching records in original order", () => {
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
    { name: "a", age: 25, country: "US", banned: 0 },
    { name: "b", age: 17, country: "US", banned: 0 },
    { name: "c", age: 40, country: "CA", banned: 1 },
    { name: "d", age: 30, country: "FR", banned: 0 },
    { name: "e", age: 22, country: "MX", banned: 0 },
  ];
  assert.deepEqual(
    filter(rule, people).map((r) => r["name"]),
    ["a", "e"],
  );
});

test("filter with empty-and matches everything; empty-or matches nothing", () => {
  const recs = [{ a: 1 }, { a: 2 }, { a: 3 }];
  assert.deepEqual(filter({ op: "and", rules: [] }, recs), recs);
  assert.deepEqual(filter({ op: "or", rules: [] }, recs), []);
});

test("RuleError thrown for an unknown op", () => {
  assert.throws(() => evaluate({ op: "wat" } as unknown as Rule, {}), RuleError);
});

test("RuleError thrown for malformed and / not / comparison nodes", () => {
  // and without an array rules
  assert.throws(() => evaluate({ op: "and" } as unknown as Rule, {}), RuleError);
  // not without a child rule
  assert.throws(() => evaluate({ op: "not" } as unknown as Rule, {}), RuleError);
  // comparison without a string field
  assert.throws(() => evaluate({ op: "eq", value: 1 } as unknown as Rule, {}), RuleError);
  // comparison with a non number/string value
  assert.throws(
    () => evaluate({ op: "gt", field: "a", value: true } as unknown as Rule, {}),
    RuleError,
  );
  // in without an array values
  assert.throws(() => evaluate({ op: "in", field: "a" } as unknown as Rule, {}), RuleError);
  // missing op entirely
  assert.throws(() => evaluate({} as unknown as Rule, {}), RuleError);
});

test("filter propagates RuleError from an invalid rule", () => {
  assert.throws(() => filter({ op: "nope" } as unknown as Rule, [{ a: 1 }]), RuleError);
});

import { test } from "node:test";
import { strict as assert } from "node:assert";
import { groupSum } from "./solution.js";

test("groups and sums by key", () => {
  const data = [
    { dept: "eng", cost: 100 },
    { dept: "eng", cost: 50 },
    { dept: "sales", cost: 70 },
  ];
  assert.deepEqual(groupSum(data, "dept", "cost"), { eng: 150, sales: 70 });
});

test("empty array -> empty object", () => {
  assert.deepEqual(groupSum([], "dept", "cost"), {});
});

test("single group", () => {
  const data = [{ k: "a", v: 1 }, { k: "a", v: 2 }, { k: "a", v: 3 }];
  assert.deepEqual(groupSum(data, "k", "v"), { a: 6 });
});

test("numeric-ish keys become string keys", () => {
  const data = [{ g: 1, n: 10 }, { g: 2, n: 5 }, { g: 1, n: 4 }];
  assert.deepEqual(groupSum(data, "g", "n"), { 1: 14, 2: 5 });
});

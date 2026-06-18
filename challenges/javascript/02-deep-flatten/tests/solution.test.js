import { test } from "node:test";
import { strict as assert } from "node:assert";
import { flatten } from "./solution.js";

test("nested arrays flatten in order", () => {
  assert.deepEqual(flatten([1, [2, [3, [4]], 5]]), [1, 2, 3, 4, 5]);
});

test("empty array", () => {
  assert.deepEqual(flatten([]), []);
});

test("interspersed empty arrays contribute nothing", () => {
  assert.deepEqual(flatten([[], [1], [], [2, [3]]]), [1, 2, 3]);
});

test("already flat array", () => {
  assert.deepEqual(flatten([1, 2, 3]), [1, 2, 3]);
});

test("deeply nested single value", () => {
  assert.deepEqual(flatten([[[[[42]]]]]), [42]);
});

test("preserves non-number leaf values and order", () => {
  assert.deepEqual(flatten(["a", ["b", [null, [false]]], 0]), ["a", "b", null, false, 0]);
});

test("does not mutate the input", () => {
  const input = [1, [2, [3]]];
  const snapshot = JSON.stringify(input);
  flatten(input);
  assert.equal(JSON.stringify(input), snapshot);
});

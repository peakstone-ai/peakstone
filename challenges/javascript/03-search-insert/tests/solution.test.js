import { test } from "node:test";
import { strict as assert } from "node:assert";
import { searchInsert } from "./solution.js";

test("target found in the middle", () => {
  assert.equal(searchInsert([1, 3, 5, 6], 5), 2);
});

test("insert in the middle", () => {
  assert.equal(searchInsert([1, 3, 5, 6], 2), 1);
});

test("insert at the end", () => {
  assert.equal(searchInsert([1, 3, 5, 6], 7), 4);
});

test("insert at the beginning", () => {
  assert.equal(searchInsert([1, 3, 5, 6], 0), 0);
});

test("empty array inserts at 0", () => {
  assert.equal(searchInsert([], 1), 0);
});

test("duplicates: returns a valid matching index", () => {
  const arr = [1, 2, 2, 2, 3];
  const idx = searchInsert(arr, 2);
  assert.equal(arr[idx], 2, "returned index should point at the target");
  assert.ok(idx >= 1 && idx <= 3, "should be one of the duplicate positions");
});

test("large array stays O(log n) correct", () => {
  const n = 1_000_000;
  const arr = Array.from({ length: n }, (_, i) => i * 2); // even numbers 0..2n-2
  assert.equal(searchInsert(arr, 999_998), 499_999); // present
  assert.equal(searchInsert(arr, 999_999), 500_000); // absent, inserts between
});

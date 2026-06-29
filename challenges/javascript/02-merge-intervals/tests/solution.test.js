import { test } from "node:test";
import { strict as assert } from "node:assert";
import { mergeIntervals } from "./solution.js";

test("empty input returns empty array", () => {
  assert.deepEqual(mergeIntervals([]), []);
});

test("single interval is returned unchanged", () => {
  assert.deepEqual(mergeIntervals([[1, 3]]), [[1, 3]]);
});

test("unsorted disjoint input is sorted", () => {
  assert.deepEqual(mergeIntervals([[3, 5], [1, 2]]), [[1, 2], [3, 5]]);
});

test("overlapping intervals merge", () => {
  assert.deepEqual(mergeIntervals([[1, 4], [2, 5]]), [[1, 5]]);
});

test("touching endpoints merge", () => {
  assert.deepEqual(mergeIntervals([[1, 3], [3, 5]]), [[1, 5]]);
});

test("containment keeps the wider interval", () => {
  assert.deepEqual(mergeIntervals([[1, 10], [2, 3], [4, 8]]), [[1, 10]]);
});

test("disjoint intervals are left separate", () => {
  assert.deepEqual(mergeIntervals([[1, 2], [4, 5]]), [[1, 2], [4, 5]]);
});

test("duplicates collapse to one", () => {
  assert.deepEqual(mergeIntervals([[1, 2], [1, 2]]), [[1, 2]]);
});

test("mixed unsorted overlapping and disjoint", () => {
  assert.deepEqual(
    mergeIntervals([[8, 10], [1, 3], [2, 6], [15, 18]]),
    [[1, 6], [8, 10], [15, 18]],
  );
});

test("the input array is not mutated", () => {
  const input = [[3, 5], [1, 2]];
  mergeIntervals(input);
  assert.deepEqual(input, [[3, 5], [1, 2]]);
});

import { test } from "node:test";
import { strict as assert } from "node:assert";
import { chunk } from "./solution.ts";

test("splits evenly and with remainder", () => {
  assert.deepEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
});

test("empty input", () => {
  assert.deepEqual(chunk<number>([], 3), []);
});

test("size larger than array", () => {
  assert.deepEqual(chunk(["a", "b"], 10), [["a", "b"]]);
});

test("invalid size throws RangeError", () => {
  assert.throws(() => chunk([1, 2], 0), RangeError);
});

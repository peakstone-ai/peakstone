import { test } from "node:test";
import { strict as assert } from "node:assert";
import { evaluateAll } from "./solution.ts";

test("evaluates with multiple variables across scopes", () => {
  assert.deepEqual(evaluateAll("a^2 + b", [{ a: 3, b: 1 }, { a: 2, b: 5 }]), [10, 9]);
});

test("preserves scope order", () => {
  assert.deepEqual(evaluateAll("x * 10", [{ x: 1 }, { x: 2 }, { x: 3 }]), [10, 20, 30]);
});

test("uses built-in functions", () => {
  assert.deepEqual(evaluateAll("sqrt(x) + max(y, 1)", [{ x: 9, y: 4 }]), [7]);
});

test("empty scopes returns empty array", () => {
  assert.deepEqual(evaluateAll("a + b", []), []);
});

test("single scope", () => {
  assert.deepEqual(evaluateAll("2 * a + 1", [{ a: 20 }]), [41]);
});

test("result is a number array", () => {
  const out = evaluateAll("a / b", [{ a: 6, b: 2 }, { a: 9, b: 3 }]);
  assert.equal(typeof out[0], "number");
  assert.deepEqual(out, [3, 3]);
});

test("compiles once and reuses for differing variable values", () => {
  const out = evaluateAll("a + b + c", [
    { a: 1, b: 2, c: 3 },
    { a: 10, b: 20, c: 30 },
  ]);
  assert.deepEqual(out, [6, 60]);
});

import { test } from "node:test";
import { strict as assert } from "node:assert";
import { evaluateAll } from "./solution.js";

test("simple variable expression over multiple scopes", () => {
  assert.deepEqual(
    evaluateAll("a + b", [{ a: 1, b: 2 }, { a: 10, b: 20 }]),
    [3, 30],
  );
});

test("preserves scope order", () => {
  assert.deepEqual(
    evaluateAll("x", [{ x: 5 }, { x: 1 }, { x: 3 }]),
    [5, 1, 3],
  );
});

test("built-in function (sqrt)", () => {
  assert.deepEqual(evaluateAll("sqrt(x^2 + y^2)", [{ x: 3, y: 4 }]), [5]);
});

test("built-in function (max) over scopes", () => {
  assert.deepEqual(
    evaluateAll("max(a, b)", [{ a: 2, b: 9 }, { a: 7, b: 3 }]),
    [9, 7],
  );
});

test("constant pi", () => {
  const [r] = evaluateAll("2 * pi", [{}]);
  assert.ok(Math.abs(r - 2 * Math.PI) < 1e-12);
});

test("empty scopes -> empty array", () => {
  assert.deepEqual(evaluateAll("a + 1", []), []);
});

test("expression with no variables, repeated scopes", () => {
  assert.deepEqual(evaluateAll("3 * 4", [{}, {}]), [12, 12]);
});

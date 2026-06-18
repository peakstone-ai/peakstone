import { test } from "node:test";
import { strict as assert } from "node:assert";
import { ok, err, map, unwrapOr, type Result } from "./solution.ts";

test("ok constructs a success result", () => {
  const r = ok(42);
  assert.deepEqual(r, { ok: true, value: 42 });
});

test("err constructs a failure result", () => {
  const r = err("boom");
  assert.deepEqual(r, { ok: false, error: "boom" });
});

test("discriminant narrows the union", () => {
  const r: Result<number, string> = ok(5);
  if (r.ok) {
    assert.equal(r.value, 5);
  } else {
    assert.fail("should be ok");
  }
});

test("map applies f to an ok value", () => {
  const r = map(ok(2), (n) => n + 1);
  assert.deepEqual(r, { ok: true, value: 3 });
});

test("map propagates an err without calling f", () => {
  let called = false;
  const r: Result<number, string> = err("nope");
  const out = map(r, (n) => {
    called = true;
    return n + 1;
  });
  assert.equal(called, false);
  assert.deepEqual(out, { ok: false, error: "nope" });
});

test("map chains", () => {
  const out = map(map(ok(10), (n) => n * 2), (n) => `=${n}`);
  assert.deepEqual(out, { ok: true, value: "=20" });
});

test("map can change the value type", () => {
  const out = map(ok(3), (n) => [n, n]);
  assert.deepEqual(out, { ok: true, value: [3, 3] });
});

test("unwrapOr returns value on ok and fallback on err", () => {
  assert.equal(unwrapOr(ok(7), 0), 7);
  assert.equal(unwrapOr(err("x") as Result<number, string>, 99), 99);
});

test("full pipeline ok and err paths", () => {
  const good: Result<number, string> = ok(4);
  const bad: Result<number, string> = err("bad");
  assert.equal(unwrapOr(map(good, (n) => n * n), -1), 16);
  assert.equal(unwrapOr(map(bad, (n) => n * n), -1), -1);
});

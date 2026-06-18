import { test } from "node:test";
import { strict as assert } from "node:assert";
import { validateUser } from "./solution.js";

test("valid user -> success with data", () => {
  const obj = { name: "Ada", age: 36, email: "ada@example.com" };
  const res = validateUser(obj);
  assert.equal(res.success, true);
  assert.deepEqual(res.data, obj);
});

test("age zero is valid", () => {
  const res = validateUser({ name: "Baby", age: 0, email: "baby@example.com" });
  assert.equal(res.success, true);
});

test("all three fields invalid -> 3 errors", () => {
  const res = validateUser({ name: "", age: -1, email: "nope" });
  assert.equal(res.success, false);
  assert.ok(Array.isArray(res.errors));
  assert.equal(res.errors.length, 3);
  for (const m of res.errors) assert.equal(typeof m, "string");
});

test("empty name is rejected", () => {
  const res = validateUser({ name: "", age: 5, email: "a@b.com" });
  assert.equal(res.success, false);
  assert.equal(res.errors.length, 1);
});

test("negative age is rejected", () => {
  const res = validateUser({ name: "A", age: -3, email: "a@b.com" });
  assert.equal(res.success, false);
  assert.equal(res.errors.length, 1);
});

test("non-integer age is rejected", () => {
  const res = validateUser({ name: "A", age: 3.5, email: "a@b.com" });
  assert.equal(res.success, false);
  assert.equal(res.errors.length, 1);
});

test("invalid email is rejected", () => {
  const res = validateUser({ name: "A", age: 5, email: "not-an-email" });
  assert.equal(res.success, false);
  assert.equal(res.errors.length, 1);
});

test("missing fields are rejected and never throws", () => {
  const res = validateUser({});
  assert.equal(res.success, false);
  assert.ok(res.errors.length >= 3);
});

test("wrong types for age (string) is rejected", () => {
  const res = validateUser({ name: "A", age: "5", email: "a@b.com" });
  assert.equal(res.success, false);
});

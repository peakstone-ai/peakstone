import { test } from "node:test";
import { strict as assert } from "node:assert";
import { LRUCache } from "./solution.ts";

test("stores and retrieves values", () => {
  const c = new LRUCache<string, number>(2);
  c.put("a", 1);
  c.put("b", 2);
  assert.equal(c.get("a"), 1);
  assert.equal(c.get("b"), 2);
  assert.equal(c.size, 2);
});

test("missing key returns undefined", () => {
  const c = new LRUCache<string, number>(2);
  assert.equal(c.get("nope"), undefined);
});

test("evicts least-recently-used on overflow", () => {
  const c = new LRUCache<string, number>(2);
  c.put("a", 1);
  c.put("b", 2);
  c.put("c", 3); // evicts "a"
  assert.equal(c.get("a"), undefined);
  assert.equal(c.get("b"), 2);
  assert.equal(c.get("c"), 3);
  assert.equal(c.size, 2);
});

test("get counts as a use and protects from eviction", () => {
  const c = new LRUCache<string, number>(2);
  c.put("a", 1);
  c.put("b", 2);
  assert.equal(c.get("a"), 1); // "a" now most-recently used
  c.put("c", 3); // evicts "b"
  assert.equal(c.get("b"), undefined);
  assert.equal(c.get("a"), 1);
  assert.equal(c.get("c"), 3);
});

test("put updates existing key and marks it used", () => {
  const c = new LRUCache<string, number>(2);
  c.put("a", 1);
  c.put("b", 2);
  c.put("a", 10); // update + use "a"
  c.put("c", 3); // evicts "b"
  assert.equal(c.get("a"), 10);
  assert.equal(c.get("b"), undefined);
  assert.equal(c.get("c"), 3);
  assert.equal(c.size, 2);
});

test("capacity of 1 keeps only the newest", () => {
  const c = new LRUCache<number, string>(1);
  c.put(1, "one");
  c.put(2, "two");
  assert.equal(c.get(1), undefined);
  assert.equal(c.get(2), "two");
  assert.equal(c.size, 1);
});

test("invalid capacity throws RangeError", () => {
  assert.throws(() => new LRUCache<string, number>(0), RangeError);
});

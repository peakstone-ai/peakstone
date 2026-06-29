import { test } from "node:test";
import { strict as assert } from "node:assert";
import { LRUCache } from "./solution.js";

test("stores and retrieves a value", () => {
  const c = new LRUCache(2);
  c.put("a", 1);
  assert.equal(c.get("a"), 1);
});

test("missing key returns undefined", () => {
  const c = new LRUCache(2);
  assert.equal(c.get("nope"), undefined);
});

test("evicts the least-recently-used entry at capacity", () => {
  const c = new LRUCache(2);
  c.put("a", 1);
  c.put("b", 2);
  c.put("c", 3); // exceeds capacity -> "a" (oldest) evicted
  assert.equal(c.get("a"), undefined);
  assert.equal(c.get("b"), 2);
  assert.equal(c.get("c"), 3);
});

test("get refreshes recency so a different key is evicted", () => {
  const c = new LRUCache(2);
  c.put("a", 1);
  c.put("b", 2);
  c.get("a"); // "a" now most-recently-used, "b" least
  c.put("c", 3); // evicts "b"
  assert.equal(c.get("b"), undefined);
  assert.equal(c.get("a"), 1);
  assert.equal(c.get("c"), 3);
});

test("updating an existing key does not grow size and refreshes recency", () => {
  const c = new LRUCache(2);
  c.put("a", 1);
  c.put("b", 2);
  c.put("a", 10); // update -> "a" most-recently-used, size stays 2
  c.put("c", 3); // evicts "b", not "a"
  assert.equal(c.get("b"), undefined);
  assert.equal(c.get("a"), 10);
  assert.equal(c.get("c"), 3);
});

test("capacity of 1 keeps only the latest entry", () => {
  const c = new LRUCache(1);
  c.put("a", 1);
  c.put("b", 2);
  assert.equal(c.get("a"), undefined);
  assert.equal(c.get("b"), 2);
});

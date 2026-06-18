import { test } from "node:test";
import { strict as assert } from "node:assert";
import { parseQuery } from "./solution.js";

test("basic pairs", () => {
  assert.deepEqual(parseQuery("a=1&b=2"), { a: "1", b: "2" });
});

test("empty string", () => {
  assert.deepEqual(parseQuery(""), {});
});

test("leading question mark", () => {
  assert.deepEqual(parseQuery("?a=1&b=2"), { a: "1", b: "2" });
});

test("repeated keys collect into array", () => {
  assert.deepEqual(parseQuery("x=1&x=2&x=3"), { x: ["1", "2", "3"] });
});

test("url-decodes values", () => {
  assert.deepEqual(parseQuery("name=John%20Doe&city=S%C3%A3o"), { name: "John Doe", city: "São" });
});

test("key without value", () => {
  assert.deepEqual(parseQuery("flag"), { flag: "" });
});

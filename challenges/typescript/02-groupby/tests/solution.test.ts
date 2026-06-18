import { test } from "node:test";
import { strict as assert } from "node:assert";
import { groupBy } from "./solution.ts";

test("groups by string key, preserving order", () => {
  const r = groupBy([1, 2, 3, 4, 5], (n) => (n % 2 === 0 ? "even" : "odd"));
  assert.deepEqual(r, { odd: [1, 3, 5], even: [2, 4] });
});

test("empty input yields empty record", () => {
  assert.deepEqual(groupBy<number, number>([], (n) => n), {});
});

test("groups by numeric key", () => {
  const r = groupBy(["a", "bb", "ccc", "dd"], (s) => s.length);
  assert.deepEqual(r, { 1: ["a"], 2: ["bb", "dd"], 3: ["ccc"] });
});

test("groups objects by a property", () => {
  const people = [
    { name: "Ana", city: "NYC" },
    { name: "Bo", city: "LA" },
    { name: "Cy", city: "NYC" },
  ];
  const r = groupBy(people, (p) => p.city);
  assert.deepEqual(r, {
    NYC: [
      { name: "Ana", city: "NYC" },
      { name: "Cy", city: "NYC" },
    ],
    LA: [{ name: "Bo", city: "LA" }],
  });
});

test("single group when keyFn is constant", () => {
  const r = groupBy([1, 2, 3], () => "all");
  assert.deepEqual(r, { all: [1, 2, 3] });
});

test("does not mutate the input array", () => {
  const input = [3, 1, 2];
  groupBy(input, (n) => n);
  assert.deepEqual(input, [3, 1, 2]);
});

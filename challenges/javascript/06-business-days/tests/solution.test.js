import { test } from "node:test";
import { strict as assert } from "node:assert";
import { businessDaysBetween } from "./solution.js";

test("Mon..Fri excludes start, counts Tue-Fri", () => {
  assert.equal(businessDaysBetween("2024-01-01", "2024-01-05"), 4);
});

test("Fri..Mon skips the weekend, counts Mon", () => {
  assert.equal(businessDaysBetween("2024-01-05", "2024-01-08"), 1);
});

test("same day -> 0", () => {
  assert.equal(businessDaysBetween("2024-01-01", "2024-01-01"), 0);
});

test("end before start -> 0", () => {
  assert.equal(businessDaysBetween("2024-01-10", "2024-01-01"), 0);
});

test("one full week (Mon..Mon) -> 5", () => {
  assert.equal(businessDaysBetween("2024-01-01", "2024-01-08"), 5);
});

test("range entirely within a weekend -> 0", () => {
  // Sat 2024-01-06 .. Sun 2024-01-07
  assert.equal(businessDaysBetween("2024-01-06", "2024-01-07"), 0);
});

test("start on a weekend still excludes start, counts weekdays after", () => {
  // Sat 2024-01-06 .. Fri 2024-01-12: Mon-Fri (5) counted
  assert.equal(businessDaysBetween("2024-01-06", "2024-01-12"), 5);
});

test("two weeks spanning two weekends", () => {
  // Mon 2024-01-01 .. Mon 2024-01-15: exclude first Mon.
  // Tue-Fri wk1 (4) + Mon-Fri wk2 (5) + final Mon (1) = 10
  assert.equal(businessDaysBetween("2024-01-01", "2024-01-15"), 10);
});

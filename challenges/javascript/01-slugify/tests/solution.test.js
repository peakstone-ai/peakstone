import { test } from "node:test";
import { strict as assert } from "node:assert";
import { slugify } from "./solution.js";

test("spaces become single hyphens", () => {
  assert.equal(slugify("Hello World"), "hello-world");
});

test("punctuation collapses and ends are trimmed", () => {
  assert.equal(slugify("  Hello,  World!  "), "hello-world");
});

test("already-clean input is unchanged", () => {
  assert.equal(slugify("already-clean"), "already-clean");
});

test("digits are preserved", () => {
  assert.equal(slugify("Top 10 Tips"), "top-10-tips");
});

test("runs of mixed separators collapse to one hyphen", () => {
  assert.equal(slugify("a---b__c"), "a-b-c");
});

test("leading and trailing junk is trimmed", () => {
  assert.equal(slugify("--Foo Bar--"), "foo-bar");
});

test("all-separator input becomes empty string", () => {
  assert.equal(slugify("@#$%"), "");
});

test("empty string stays empty", () => {
  assert.equal(slugify(""), "");
});

test("non-ASCII letters act as separators", () => {
  assert.equal(slugify("café crème"), "caf-cr-me");
});

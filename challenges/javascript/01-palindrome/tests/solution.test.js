import { test } from "node:test";
import { strict as assert } from "node:assert";
import { isPalindrome } from "./solution.js";

test("classic palindrome ignoring punctuation/case", () => {
  assert.equal(isPalindrome("A man, a plan, a canal: Panama"), true);
});

test("non-palindrome", () => {
  assert.equal(isPalindrome("race a car"), false);
});

test("empty string is a palindrome", () => {
  assert.equal(isPalindrome(""), true);
});

test("alphanumeric mix", () => {
  assert.equal(isPalindrome("0P"), false);
  assert.equal(isPalindrome("ab_a"), true);
});

import { test } from "node:test";
import { strict as assert } from "node:assert";
import { retry } from "./solution.js";

// fn that rejects the first `failures` times, then resolves with `value`.
function flaky(failures, value) {
  let calls = 0;
  const fn = async () => {
    calls++;
    if (calls <= failures) {
      throw new Error(`fail #${calls}`);
    }
    return value;
  };
  fn.calls = () => calls;
  return fn;
}

test("resolves immediately when fn succeeds first try", async () => {
  const fn = flaky(0, "ok");
  const result = await retry(fn, { retries: 3, baseDelayMs: 1 });
  assert.equal(result, "ok");
  assert.equal(fn.calls(), 1);
});

test("retries until success and returns the value", async () => {
  const fn = flaky(2, 42);
  const result = await retry(fn, { retries: 3, baseDelayMs: 1 });
  assert.equal(result, 42);
  assert.equal(fn.calls(), 3); // 2 failures + 1 success
});

test("rejects with the last error after exhausting retries", async () => {
  let calls = 0;
  const fn = async () => {
    calls++;
    throw new Error(`boom ${calls}`);
  };
  await assert.rejects(
    () => retry(fn, { retries: 2, baseDelayMs: 1 }),
    /boom 3/,
  );
  assert.equal(calls, 3); // 1 initial + 2 retries
});

test("retries = 0 means exactly one call", async () => {
  let calls = 0;
  const fn = async () => {
    calls++;
    throw new Error("nope");
  };
  await assert.rejects(() => retry(fn, { retries: 0, baseDelayMs: 1 }));
  assert.equal(calls, 1);
});

test("uses default options when none provided", async () => {
  const fn = flaky(1, "done");
  const result = await retry(fn);
  assert.equal(result, "done");
  assert.equal(fn.calls(), 2);
});

test("waits with exponential backoff between attempts", async () => {
  const fn = flaky(2, "ok");
  const start = Date.now();
  await retry(fn, { retries: 3, baseDelayMs: 20 });
  const elapsed = Date.now() - start;
  // backoff before retry 0 (20ms) + before retry 1 (40ms) = 60ms minimum
  assert.ok(elapsed >= 55, `expected >= ~60ms of backoff, got ${elapsed}ms`);
});

import { test } from "node:test";
import { strict as assert } from "node:assert";
import { memoizeAsync } from "./solution.js";

const tick = () => new Promise((res) => setTimeout(res, 1));

test("concurrent identical calls share one in-flight promise (dedup)", async () => {
  let calls = 0;
  const fn = async (x) => {
    calls++;
    await tick();
    return x * 2;
  };
  const m = memoizeAsync(fn, { ttlMs: 1000, now: () => 0 });
  const [a, b, c] = await Promise.all([m(5), m(5), m(5)]);
  assert.equal(a, 10);
  assert.equal(b, 10);
  assert.equal(c, 10);
  assert.equal(calls, 1);
});

test("cache hit within ttl does not call fn again", async () => {
  let calls = 0;
  let t = 1000;
  const fn = async (x) => {
    calls++;
    return x + 1;
  };
  const m = memoizeAsync(fn, { ttlMs: 100, now: () => t });
  assert.equal(await m(7), 8);
  t = 1050; // still within ttl
  assert.equal(await m(7), 8);
  assert.equal(calls, 1);
});

test("entry expires after ttl, fn is called again", async () => {
  let calls = 0;
  let t = 1000;
  const fn = async (x) => {
    calls++;
    return x;
  };
  const m = memoizeAsync(fn, { ttlMs: 100, now: () => t });
  await m("k");
  assert.equal(calls, 1);
  t = 1200; // past ttl
  await m("k");
  assert.equal(calls, 2);
});

test("different keys are cached independently", async () => {
  let calls = 0;
  const fn = async (x) => {
    calls++;
    return x * 10;
  };
  const m = memoizeAsync(fn, { ttlMs: 1000, now: () => 0 });
  assert.equal(await m(1), 10);
  assert.equal(await m(2), 20);
  assert.equal(await m(1), 10); // cached
  assert.equal(calls, 2);
});

test("multiple arguments form the key", async () => {
  let calls = 0;
  const fn = async (a, b) => {
    calls++;
    return a + b;
  };
  const m = memoizeAsync(fn, { ttlMs: 1000, now: () => 0 });
  assert.equal(await m(1, 2), 3);
  assert.equal(await m(1, 2), 3); // hit
  assert.equal(await m(2, 1), 3); // different key
  assert.equal(calls, 2);
});

test("rejections are not cached; next call retries", async () => {
  let calls = 0;
  const fn = async () => {
    calls++;
    throw new Error(`boom ${calls}`);
  };
  const m = memoizeAsync(fn, { ttlMs: 1000, now: () => 0 });
  await assert.rejects(() => m("x"), /boom 1/);
  await assert.rejects(() => m("x"), /boom 2/);
  assert.equal(calls, 2);
});

test("defaults to Date.now when no clock provided", async () => {
  let calls = 0;
  const fn = async (x) => {
    calls++;
    return x;
  };
  const m = memoizeAsync(fn, { ttlMs: 10000 });
  await m(42);
  await m(42);
  assert.equal(calls, 1);
});

test("expiry boundary: exactly ttl old is treated as expired", async () => {
  let calls = 0;
  let t = 0;
  const fn = async (x) => {
    calls++;
    return x;
  };
  const m = memoizeAsync(fn, { ttlMs: 100, now: () => t });
  await m("b"); // stored at time 0
  t = 100; // age === ttl -> not < ttl -> expired
  await m("b");
  assert.equal(calls, 2);
});

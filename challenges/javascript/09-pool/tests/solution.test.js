import { test } from "node:test";
import { strict as assert } from "node:assert";
import { pool } from "./solution.js";

const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

// Build instrumented thunks that track peak concurrency.
function makeTracker() {
  const state = { active: 0, peak: 0, starts: [] };
  const thunk = (id, ms) => async () => {
    state.active++;
    state.peak = Math.max(state.peak, state.active);
    state.starts.push(id);
    await sleep(ms);
    state.active--;
    return id;
  };
  return { state, thunk };
}

test("results are returned in original order, not completion order", async () => {
  const { thunk } = makeTracker();
  // 'a' is slowest but must still come first in the results.
  const out = await pool([thunk("a", 30), thunk("b", 5), thunk("c", 15)], 3);
  assert.deepEqual(out, ["a", "b", "c"]);
});

test("peak concurrency never exceeds the limit", async () => {
  const { state, thunk } = makeTracker();
  const thunks = [];
  for (let i = 0; i < 10; i++) thunks.push(thunk(i, 10));
  const out = await pool(thunks, 3);
  assert.deepEqual(out, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.ok(state.peak <= 3, `peak was ${state.peak}, expected <= 3`);
  assert.equal(state.peak, 3); // pool should actually reach the limit
});

test("concurrency of 1 runs strictly sequentially", async () => {
  const { state, thunk } = makeTracker();
  const thunks = [thunk("x", 10), thunk("y", 10), thunk("z", 10)];
  const out = await pool(thunks, 1);
  assert.deepEqual(out, ["x", "y", "z"]);
  assert.equal(state.peak, 1);
});

test("empty thunks -> empty array", async () => {
  const out = await pool([], 4);
  assert.deepEqual(out, []);
});

test("concurrency larger than number of thunks", async () => {
  const { state, thunk } = makeTracker();
  const thunks = [thunk(1, 5), thunk(2, 5)];
  const out = await pool(thunks, 10);
  assert.deepEqual(out, [1, 2]);
  assert.equal(state.peak, 2);
});

test("all thunks actually run exactly once", async () => {
  let count = 0;
  const thunks = [];
  for (let i = 0; i < 6; i++) {
    thunks.push(async () => {
      count++;
      await sleep(2);
      return i * i;
    });
  }
  const out = await pool(thunks, 2);
  assert.deepEqual(out, [0, 1, 4, 9, 16, 25]);
  assert.equal(count, 6);
});

test("pool keeps the slots full as tasks finish", async () => {
  // Mix of fast and slow tasks; with limit 2, a fast finisher should let a new
  // task start while a slow one is still running -> peak hits 2 repeatedly.
  const { state, thunk } = makeTracker();
  const thunks = [
    thunk("a", 40),
    thunk("b", 5),
    thunk("c", 5),
    thunk("d", 5),
  ];
  const out = await pool(thunks, 2);
  assert.deepEqual(out, ["a", "b", "c", "d"]);
  assert.equal(state.peak, 2);
});

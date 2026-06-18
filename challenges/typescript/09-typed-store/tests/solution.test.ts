import { test } from "node:test";
import { strict as assert } from "node:assert";
import { createStore } from "./solution.ts";

type Action = { type: "inc" } | { type: "add"; by: number } | { type: "reset" };

function counterReducer(state: number, action: Action): number {
  switch (action.type) {
    case "inc":
      return state + 1;
    case "add":
      return state + action.by;
    case "reset":
      return 0;
  }
}

function makeCounter(initial = 0) {
  return createStore<number, Action>(counterReducer, initial);
}

test("starts at the initial state", () => {
  assert.equal(makeCounter(5).getState(), 5);
});

test("dispatch updates state via the reducer", () => {
  const s = makeCounter();
  s.dispatch({ type: "inc" });
  assert.equal(s.getState(), 1);
  s.dispatch({ type: "add", by: 5 });
  assert.equal(s.getState(), 6);
  s.dispatch({ type: "reset" });
  assert.equal(s.getState(), 0);
});

test("subscribers fire on every dispatch", () => {
  const s = makeCounter();
  let calls = 0;
  s.subscribe(() => {
    calls += 1;
  });
  s.dispatch({ type: "inc" });
  s.dispatch({ type: "inc" });
  assert.equal(calls, 2);
});

test("multiple subscribers all fire", () => {
  const s = makeCounter();
  let a = 0;
  let b = 0;
  s.subscribe(() => {
    a += 1;
  });
  s.subscribe(() => {
    b += 1;
  });
  s.dispatch({ type: "inc" });
  assert.equal(a, 1);
  assert.equal(b, 1);
});

test("unsubscribe stops notifications", () => {
  const s = makeCounter();
  let calls = 0;
  const off = s.subscribe(() => {
    calls += 1;
  });
  s.dispatch({ type: "inc" });
  off();
  s.dispatch({ type: "inc" });
  assert.equal(calls, 1);
  assert.equal(s.getState(), 2);
});

test("unsubscribing twice is harmless", () => {
  const s = makeCounter();
  const off = s.subscribe(() => {});
  off();
  assert.doesNotThrow(() => off());
});

test("subscriber sees the updated state when notified", () => {
  const s = makeCounter();
  const seen: number[] = [];
  s.subscribe(() => {
    seen.push(s.getState());
  });
  s.dispatch({ type: "inc" });
  s.dispatch({ type: "add", by: 10 });
  assert.deepEqual(seen, [1, 11]);
});

test("works with an object state shape", () => {
  type S = { count: number; label: string };
  type A = { type: "bump" } | { type: "label"; text: string };
  const s = createStore<S, A>((state, action) => {
    switch (action.type) {
      case "bump":
        return { ...state, count: state.count + 1 };
      case "label":
        return { ...state, label: action.text };
    }
  }, { count: 0, label: "" });
  s.dispatch({ type: "bump" });
  s.dispatch({ type: "label", text: "hi" });
  assert.deepEqual(s.getState(), { count: 1, label: "hi" });
});

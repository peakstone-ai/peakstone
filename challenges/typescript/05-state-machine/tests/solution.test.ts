import { test } from "node:test";
import { strict as assert } from "node:assert";
import { createMachine } from "./solution.ts";

type S = "idle" | "running" | "paused";
type E = "start" | "pause" | "stop";

function make() {
  return createMachine<S, E>({
    initial: "idle",
    states: {
      idle: { start: "running" },
      running: { pause: "paused", stop: "idle" },
      paused: { start: "running", stop: "idle" },
    },
  });
}

test("starts in the initial state", () => {
  assert.equal(make().state, "idle");
});

test("valid transition changes state", () => {
  const m = make();
  m.send("start");
  assert.equal(m.state, "running");
});

test("invalid transition is ignored", () => {
  const m = make();
  m.send("pause"); // not allowed from idle
  assert.equal(m.state, "idle");
});

test("can reflects available transitions", () => {
  const m = make();
  assert.equal(m.can("start"), true);
  assert.equal(m.can("pause"), false);
  assert.equal(m.can("stop"), false);
});

test("can updates after a transition", () => {
  const m = make();
  m.send("start");
  assert.equal(m.can("pause"), true);
  assert.equal(m.can("stop"), true);
  assert.equal(m.can("start"), false);
});

test("multi-step sequence", () => {
  const m = make();
  m.send("start"); // running
  m.send("pause"); // paused
  assert.equal(m.state, "paused");
  m.send("start"); // running
  m.send("stop"); // idle
  assert.equal(m.state, "idle");
});

test("self / terminal states with no outgoing events ignore everything", () => {
  const m = createMachine<"on" | "done", "finish" | "go">({
    initial: "on",
    states: {
      on: { finish: "done" },
      done: {},
    },
  });
  m.send("finish");
  assert.equal(m.state, "done");
  m.send("go");
  m.send("finish");
  assert.equal(m.state, "done");
  assert.equal(m.can("go"), false);
});

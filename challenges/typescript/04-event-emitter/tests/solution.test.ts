import { test } from "node:test";
import { strict as assert } from "node:assert";
import { EventEmitter } from "./solution.ts";

type Events = {
  message: [text: string];
  count: [n: number, label: string];
};

test("calls a registered listener with args", () => {
  const ee = new EventEmitter<Events>();
  const seen: string[] = [];
  ee.on("message", (text) => seen.push(text));
  ee.emit("message", "hi");
  assert.deepEqual(seen, ["hi"]);
});

test("multiple listeners fire in registration order", () => {
  const ee = new EventEmitter<Events>();
  const order: number[] = [];
  ee.on("message", () => order.push(1));
  ee.on("message", () => order.push(2));
  ee.on("message", () => order.push(3));
  ee.emit("message", "x");
  assert.deepEqual(order, [1, 2, 3]);
});

test("passes multiple typed args", () => {
  const ee = new EventEmitter<Events>();
  let received: [number, string] | undefined;
  ee.on("count", (n, label) => {
    received = [n, label];
  });
  ee.emit("count", 7, "items");
  assert.deepEqual(received, [7, "items"]);
});

test("returned unsubscribe removes the listener", () => {
  const ee = new EventEmitter<Events>();
  const seen: string[] = [];
  const unsub = ee.on("message", (t) => seen.push(t));
  ee.emit("message", "a");
  unsub();
  ee.emit("message", "b");
  assert.deepEqual(seen, ["a"]);
});

test("off removes a specific listener, leaving others", () => {
  const ee = new EventEmitter<Events>();
  const seen: string[] = [];
  const a = (t: string) => seen.push("a:" + t);
  const b = (t: string) => seen.push("b:" + t);
  ee.on("message", a);
  ee.on("message", b);
  ee.off("message", a);
  ee.emit("message", "x");
  assert.deepEqual(seen, ["b:x"]);
});

test("emitting an event with no listeners is a no-op", () => {
  const ee = new EventEmitter<Events>();
  assert.doesNotThrow(() => ee.emit("message", "nobody"));
});

test("off on an unregistered listener is a no-op", () => {
  const ee = new EventEmitter<Events>();
  assert.doesNotThrow(() => ee.off("message", () => {}));
});

test("the same function registered twice fires twice", () => {
  const ee = new EventEmitter<Events>();
  let calls = 0;
  const fn = () => {
    calls += 1;
  };
  ee.on("message", fn);
  ee.on("message", fn);
  ee.emit("message", "x");
  assert.equal(calls, 2);
});

# Typed finite state machine

Implement **`solution.ts`** exporting a factory that builds a typed finite state machine:

```ts
export interface Machine<S extends string, E extends string> {
  state: S;
  send(event: E): void;
  can(event: E): boolean;
}

export function createMachine<S extends string, E extends string>(config: {
  initial: S;
  states: Record<S, Partial<Record<E, S>>>;
}): Machine<S, E>;
```

`config.states` maps each state to a partial map from an event to the next state.

The returned machine:

- starts in `config.initial` (exposed as the mutable property `state`);
- `send(event)` transitions to the target state if the **current** state defines a
  transition for `event`; otherwise it is **ignored** (the state is unchanged, no throw);
- `can(event)` returns `true` iff the current state defines a transition for `event`.

Example:

```ts
const m = createMachine({
  initial: "idle",
  states: {
    idle: { start: "running" },
    running: { pause: "paused", stop: "idle" },
    paused: { start: "running", stop: "idle" },
  },
});

m.state;            // "idle"
m.can("start");     // true
m.can("pause");     // false
m.send("pause");    // ignored
m.state;            // "idle"
m.send("start");
m.state;            // "running"
m.send("stop");
m.state;            // "idle"
```

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.

# Typed redux-style store

Implement **`solution.ts`** exporting a generic store factory (a tiny redux).

Export exactly one function. It is generic over the state type `S` and the action type
`A`, and returns a store object:

```ts
export function createStore<S, A>(
  reducer: (state: S, action: A) => S,
  initial: S,
): {
  getState(): S;
  dispatch(action: A): void;
  subscribe(fn: () => void): () => void;
};
```

Behavior:

- `getState()` returns the **current** state (starts as `initial`).
- `dispatch(action)` computes the next state as `reducer(currentState, action)`,
  replaces the current state with it, then notifies **all** current subscribers (calls
  each subscriber function once, with no arguments).
- `subscribe(fn)` registers `fn` and returns an **unsubscribe** function. Calling the
  returned function removes `fn` so it is no longer notified on future dispatches.
  Unsubscribing the same listener twice is harmless.

The store must be fully generic: `S` and `A` are inferred from the `reducer` and
`initial` arguments, and `dispatch` must only accept values of the action type `A`
(typically a discriminated union).

Example:
```ts
type Action = { type: "inc" } | { type: "add"; by: number };

const store = createStore<number, Action>((state, action) => {
  switch (action.type) {
    case "inc": return state + 1;
    case "add": return state + action.by;
  }
}, 0);

store.getState();            // 0
const off = store.subscribe(() => { /* ... */ });
store.dispatch({ type: "inc" });        // state -> 1, subscriber fired
store.dispatch({ type: "add", by: 5 }); // state -> 6
off();                                    // unsubscribe
```

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.

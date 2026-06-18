# Typed event emitter

Implement **`solution.ts`** exporting a generic, fully typed event emitter:

```ts
export class EventEmitter<Events extends Record<string, unknown[]>> {
  on<E extends keyof Events>(event: E, fn: (...args: Events[E]) => void): () => void;
  off<E extends keyof Events>(event: E, fn: (...args: Events[E]) => void): void;
  emit<E extends keyof Events>(event: E, ...args: Events[E]): void;
}
```

`Events` maps an event name to the **tuple of argument types** its listeners receive.

- `on(event, fn)` registers a listener and returns an **unsubscribe** function. Calling
  the returned function removes that exact listener.
- `off(event, fn)` removes a previously registered listener. Removing a listener that is
  not registered is a no-op.
- `emit(event, ...args)` calls every listener registered for `event`, **in the order they
  were registered**, passing `args`. Emitting an event with no listeners is a no-op.
- The same function may be registered more than once; each registration is independent.

Example:

```ts
type Events = {
  message: [text: string];
  count: [n: number, label: string];
};

const ee = new EventEmitter<Events>();
const unsub = ee.on("message", (text) => console.log(text));
ee.emit("message", "hi"); // logs "hi"
unsub();
ee.emit("message", "bye"); // nothing logged
```

Keep it fully typed (must pass `tsc --noEmit` in strict mode). Do not use `any` in the
public API.

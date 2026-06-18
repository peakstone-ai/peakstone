type Listener<Args extends unknown[]> = (...args: Args) => void;

export class EventEmitter<Events extends Record<string, unknown[]>> {
  // Per-event listener arrays. The value type is erased to `unknown[]` args
  // here; the public methods re-establish the precise per-event type.
  private readonly listeners = new Map<keyof Events, Array<Listener<unknown[]>>>();

  on<E extends keyof Events>(event: E, fn: Listener<Events[E]>): () => void {
    const list = this.listeners.get(event) ?? [];
    list.push(fn as unknown as Listener<unknown[]>);
    this.listeners.set(event, list);
    return () => this.off(event, fn);
  }

  off<E extends keyof Events>(event: E, fn: Listener<Events[E]>): void {
    const list = this.listeners.get(event);
    if (!list) return;
    const idx = list.indexOf(fn as unknown as Listener<unknown[]>);
    if (idx !== -1) list.splice(idx, 1);
  }

  emit<E extends keyof Events>(event: E, ...args: Events[E]): void {
    const list = this.listeners.get(event);
    if (!list) return;
    // copy so that (un)subscribing during emit doesn't disturb this dispatch
    for (const fn of [...list]) {
      (fn as unknown as Listener<Events[E]>)(...args);
    }
  }
}

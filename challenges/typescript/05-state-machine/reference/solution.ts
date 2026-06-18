export interface Machine<S extends string, E extends string> {
  state: S;
  send(event: E): void;
  can(event: E): boolean;
}

export function createMachine<S extends string, E extends string>(config: {
  initial: S;
  states: Record<S, Partial<Record<E, S>>>;
}): Machine<S, E> {
  return {
    state: config.initial,
    can(event: E): boolean {
      return config.states[this.state][event] !== undefined;
    },
    send(event: E): void {
      const next = config.states[this.state][event];
      if (next !== undefined) {
        this.state = next;
      }
    },
  };
}

export function createStore<S, A>(
  reducer: (state: S, action: A) => S,
  initial: S,
): {
  getState(): S;
  dispatch(action: A): void;
  subscribe(fn: () => void): () => void;
} {
  let state = initial;
  const listeners = new Set<() => void>();

  return {
    getState(): S {
      return state;
    },
    dispatch(action: A): void {
      state = reducer(state, action);
      for (const fn of [...listeners]) {
        fn();
      }
    },
    subscribe(fn: () => void): () => void {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
  };
}

export function memoizeAsync(fn, { ttlMs, now = Date.now } = {}) {
  // key -> { promise } while pending, replaced with { value, time } once resolved.
  const cache = new Map();

  return function memoized(...args) {
    const key = JSON.stringify(args);
    const entry = cache.get(key);

    if (entry) {
      if (entry.pending) {
        // In-flight: share the same promise.
        return entry.promise;
      }
      if (now() - entry.time < ttlMs) {
        // Fresh cached value.
        return Promise.resolve(entry.value);
      }
      // Expired; fall through and recompute.
    }

    const promise = Promise.resolve()
      .then(() => fn.apply(this, args))
      .then(
        (value) => {
          cache.set(key, { pending: false, value, time: now() });
          return value;
        },
        (err) => {
          // Do not cache failures.
          if (cache.get(key)?.pending) cache.delete(key);
          throw err;
        },
      );

    cache.set(key, { pending: true, promise });
    return promise;
  };
}

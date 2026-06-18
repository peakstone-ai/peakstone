export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

export function ok<T>(v: T): Result<T, never> {
  return { ok: true, value: v };
}

export function err<E>(e: E): Result<never, E> {
  return { ok: false, error: e };
}

export function map<T, U, E>(r: Result<T, E>, f: (t: T) => U): Result<U, E> {
  if (r.ok) {
    return ok(f(r.value));
  }
  return r;
}

export function unwrapOr<T, E>(r: Result<T, E>, fallback: T): T {
  return r.ok ? r.value : fallback;
}

"use client"; // error boundaries must be client components

// Catches uncaught render exceptions (a bug, not an expected state like "API unreachable" —
// fetch failures are modeled as ApiResult values, review R23) and offers a retry.
export default function ErrorPage({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <main className="mx-auto max-w-3xl px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="mt-3 text-sm text-stone-400">
        The page failed to render{error.digest ? ` (digest ${error.digest})` : ""}. This is a bug
        on our side, not yours.
      </p>
      <button
        onClick={() => unstable_retry()}
        className="mt-6 rounded-md bg-emerald-700 px-4 py-1.5 text-sm text-white hover:bg-emerald-600"
      >
        Try again
      </button>
    </main>
  );
}

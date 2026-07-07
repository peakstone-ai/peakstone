import Link from "next/link";

// Rendered (with a real 404 status) whenever a page calls notFound() — an unknown model family,
// run hash, or challenge id — or the route itself doesn't exist (review R23).
export default function NotFound() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-16 text-center">
      <h1 className="text-2xl font-semibold">Not found</h1>
      <p className="mt-3 text-sm text-stone-400">
        No model, run, or challenge lives at this address — it may have been retired, or the link
        is stale.
      </p>
      <p className="mt-6 text-sm">
        <Link href="/leaderboard" className="text-emerald-400 hover:underline">
          Back to the leaderboard →
        </Link>
      </p>
    </main>
  );
}

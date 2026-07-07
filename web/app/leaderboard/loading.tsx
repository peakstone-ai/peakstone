// Streaming fallback while a dynamic page's data loads (every page is force-dynamic; the API
// fetch usually answers from the 30s cache, so this shows only on cold hits).
export default function Loading() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-16 text-center text-sm text-stone-500">
      Loading…
    </main>
  );
}

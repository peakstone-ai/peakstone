import Link from "next/link";
import { notFound } from "next/navigation";
import { getRun } from "@/lib/api";
import { ApiDown, ScoreBar, Trust } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function RunPage({
  params,
}: {
  params: Promise<{ hash: string }>;
}) {
  const { hash } = await params;
  const res = await getRun(decodeURIComponent(hash));
  if (!res.ok) {
    if (res.notFound) notFound(); // unknown bundle hash → a real 404 (R23)
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  const data = res.data;
  const short = data.bundle_hash.slice(0, 12);

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      {data.family ? (
        <Link
          href={`/models/${encodeURIComponent(data.family)}`}
          className="text-sm text-stone-500 hover:text-stone-300"
        >
          ← {data.family}
        </Link>
      ) : (
        <Link href="/leaderboard" className="text-sm text-stone-500 hover:text-stone-300">
          ← leaderboard
        </Link>
      )}
      <h1 className="mt-2 text-2xl font-semibold">
        {data.family ?? "Run"} {data.artifact ? <span className="text-stone-400">{data.artifact}</span> : null}
      </h1>
      <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-stone-400">
        <span>{data.n} challenge{data.n === 1 ? "" : "s"}</span>
        {data.context ? <span>· {Math.round(data.context / 1024)}K ctx</span> : null}
        <span>· {data.suite}</span>
        <span>· <Trust t={data.trust_tier} /></span>
        <span className="text-stone-600">· {short}</span>
      </p>

      <p className="mt-4 text-sm text-stone-500">Select a challenge to see the model’s proposed solution.</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-stone-500">
              <th className="py-2 pr-4 font-medium">Challenge</th>
              <th className="py-2 pr-4 font-medium">Category</th>
              <th className="py-2 pr-4 font-medium">Score</th>
              <th className="py-2 pr-4 font-medium">Tests</th>
              <th className="py-2 pr-4 font-medium">Note</th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((r) => (
              <tr key={r.challenge} className="border-t border-stone-800 hover:bg-stone-900/40">
                <td className="py-2 pr-4">
                  <Link
                    href={`/runs/${encodeURIComponent(data.bundle_hash)}/${encodeURIComponent(r.challenge)}`}
                    className="font-medium text-stone-100 hover:text-emerald-400"
                  >
                    {r.challenge}
                  </Link>
                </td>
                <td className="py-2 pr-4 text-stone-400">{r.category ?? r.verification ?? "—"}</td>
                <td className="py-2 pr-4">
                  <ScoreBar v={r.final} />
                </td>
                <td className="py-2 pr-4 tabular-nums text-stone-400">
                  {r.total ? `${r.passed ?? 0}/${r.total}` : "—"}
                </td>
                <td className="py-2 pr-4 text-xs text-amber-400/80">{r.error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

import Link from "next/link";
import { notFound } from "next/navigation";
import { getModel } from "@/lib/api";
import { ApiDown, ScoreBar, Trust } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function ModelPage({
  params,
}: {
  params: Promise<{ family: string }>;
}) {
  const { family } = await params;
  const data = await getModel(decodeURIComponent(family));
  if (data === null) {
    // distinguish "API down" from "unknown family" isn't possible from null alone; show API-down
    // card, but a 404-style page if the API returned 404 is handled by getModel returning null too.
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  if (!data.family) notFound();

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/" className="text-sm text-stone-500 hover:text-stone-300">
        ← leaderboard
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">{data.family}</h1>
      <p className="mt-1 text-sm text-stone-400">
        {data.vendor ? `${data.vendor} · ` : ""}
        {data.release_date ? `released ${data.release_date} · ` : ""}
        {data.n_runs} run{data.n_runs === 1 ? "" : "s"} — every distinct config is its own row (no
        collapsing).
      </p>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-stone-500">
              <th className="py-2 pr-4 font-medium">Quant</th>
              <th className="py-2 pr-4 font-medium">Ctx</th>
              <th className="py-2 pr-4 font-medium">VRAM</th>
              <th className="py-2 pr-4 font-medium">Code score</th>
              <th className="py-2 pr-4 font-medium">Safety</th>
              <th className="py-2 pr-4 font-medium">Engine</th>
              <th className="py-2 pr-4 font-medium">Trust</th>
              <th className="py-2 pr-4 font-medium">Suite</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.run.bundle_hash} className="border-t border-stone-800">
                <td className="py-2 pr-4 text-stone-200">{r.run.artifact}</td>
                <td className="py-2 pr-4 tabular-nums text-stone-400">
                  {r.run.context ? `${Math.round(r.run.context / 1024)}K` : "—"}
                </td>
                <td className="py-2 pr-4 tabular-nums text-stone-400">
                  {r.run.vram_gb ?? "?"} GB
                </td>
                <td className="py-2 pr-4">
                  <ScoreBar v={r.code_score} />
                </td>
                <td className="py-2 pr-4 tabular-nums text-stone-300">
                  {r.safety_score == null ? "—" : r.safety_score.toFixed(2)}
                </td>
                <td className="py-2 pr-4 text-stone-400">
                  {r.run.engine?.name ?? "?"} {r.run.engine?.version ?? ""}
                </td>
                <td className="py-2 pr-4">
                  <Trust t={r.run.trust_tier} />
                  {r.run.submitter ? (
                    <span className="ml-1 text-xs text-stone-500">@{r.run.submitter}</span>
                  ) : null}
                </td>
                <td className="py-2 pr-4 text-stone-500">{r.suite}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

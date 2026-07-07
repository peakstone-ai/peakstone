import Link from "next/link";
import { notFound } from "next/navigation";
import { getModel } from "@/lib/api";
import { ApiDown, DataTable, ScoreBar, Trust } from "@/components/ui";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ family: string }> }) {
  const { family } = await params;
  return { title: `${decodeURIComponent(family)} — Peakstone` };
}

export default async function ModelPage({
  params,
}: {
  params: Promise<{ family: string }>;
}) {
  const { family } = await params;
  const res = await getModel(decodeURIComponent(family));
  if (!res.ok) {
    if (res.notFound) notFound(); // unknown family → a real 404, not an "API down" card (R23)
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  const data = res.data;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/leaderboard" className="text-sm text-stone-500 hover:text-stone-300">
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
        <DataTable
          head={[
            { label: "Artifact", title: "the exact model file benchmarked (quant build)" },
            "Ctx", "VRAM", "Code score", "Safety", "Efficiency", "Engine", "Trust",
            { label: "Suite", title: "the level (versioned challenge selection) the run executed" },
          ]}
        >
          {data.runs.map((r) => (
              <tr key={r.run.bundle_hash} className="border-t border-stone-800">
                <td className="py-2 pr-4">
                  <Link
                    href={`/runs/${encodeURIComponent(r.run.bundle_hash)}`}
                    className="text-stone-200 hover:text-emerald-400"
                  >
                    {r.run.artifact}
                  </Link>
                </td>
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
                <td className="py-2 pr-4 text-xs tabular-nums text-stone-400">
                  {r.metrics?.loc != null ? `${Math.round(r.metrics.loc)} LOC` : ""}
                  {r.metrics?.peak_rss_mb != null ? ` · ${Math.round(r.metrics.peak_rss_mb)} MB` : ""}
                  {r.metrics?.loc == null && r.metrics?.peak_rss_mb == null ? "—" : ""}
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
        </DataTable>
      </div>
    </main>
  );
}

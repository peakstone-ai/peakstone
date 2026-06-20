import Link from "next/link";
import { getFacets, getLeaderboard } from "@/lib/api";
import { ApiDown, ScoreBar, Trust } from "@/components/ui";
import { SelectFilter } from "@/components/Filters";

export const dynamic = "force-dynamic";

const VRAM_PRESETS: [string, string][] = [
  ["All", ""],
  ["≤8 GB", "8"],
  ["≤12 GB", "12"],
  ["≤16 GB", "16"],
  ["≤24 GB", "24"],
  ["≤48 GB", "48"],
];

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const vram = sp.max_vram_gb ?? "";
  const [data, facets] = await Promise.all([getLeaderboard(sp), getFacets()]);

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Coder leaderboard</h1>
      <p className="mt-1 max-w-2xl text-sm text-stone-400">
        The best <em>qualifying</em> run per model family, ranked by code score. Safety/honesty is
        scored separately (not blended into coding ability). Runs are never collapsed — quants,
        contexts, and hardware are distinct.
      </p>

      <div className="my-5 flex flex-wrap items-center gap-2">
        <span className="text-sm text-stone-500">Fits my hardware:</span>
        {VRAM_PRESETS.map(([label, val]) => {
          const active = vram === val;
          const params = new URLSearchParams();
          for (const k of ["quant", "trust", "suite", "version"]) {
            if (sp[k]) params.set(k, sp[k] as string);
          }
          if (val) params.set("max_vram_gb", val);
          const qs = params.toString();
          return (
            <Link
              key={label}
              href={qs ? `/?${qs}` : "/"}
              className={`rounded-full px-3 py-1 text-sm transition-colors ${
                active
                  ? "bg-emerald-600 text-white"
                  : "bg-stone-800 text-stone-300 hover:bg-stone-700"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </div>

      {facets && (facets.quants.length > 0 || facets.trust_tiers.length > 1) && (
        <div className="mb-5 flex flex-wrap items-center gap-4">
          {facets.quants.length > 0 && (
            <SelectFilter param="quant" label="Quant" options={facets.quants} />
          )}
          {facets.trust_tiers.length > 1 && (
            <SelectFilter param="trust" label="Trust" options={facets.trust_tiers} allLabel="Any" />
          )}
        </div>
      )}

      {!data ? (
        <ApiDown />
      ) : data.leaderboard.length === 0 ? (
        <p className="text-stone-400">
          No runs yet{vram ? ` that fit in ≤${vram} GB VRAM` : ""}.{" "}
          <Link href="/submit" className="text-emerald-400 hover:underline">
            Submit one
          </Link>
          .
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-stone-500">
                <th className="py-2 pr-2 font-medium">#</th>
                <th className="py-2 pr-4 font-medium">Model</th>
                <th className="py-2 pr-4 font-medium">Code score</th>
                <th className="py-2 pr-4 font-medium">Safety</th>
                <th className="py-2 pr-4 font-medium">Solved</th>
                <th className="py-2 pr-4 font-medium">Best run</th>
              </tr>
            </thead>
            <tbody>
              {data.leaderboard.map((r) => (
                <tr key={r.family} className="border-t border-stone-800">
                  <td className="py-2 pr-2 tabular-nums text-stone-500">{r.rank}</td>
                  <td className="py-2 pr-4">
                    <Link
                      href={`/models/${encodeURIComponent(r.family)}`}
                      className="font-medium text-stone-100 hover:text-emerald-400"
                    >
                      {r.family}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">
                    <ScoreBar v={r.code_score} />
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.safety_score == null ? "—" : r.safety_score.toFixed(2)}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.solved}/{r.n_code}
                  </td>
                  <td className="py-2 pr-4 text-stone-400">
                    <span className="text-stone-300">{r.run.artifact}</span> ·{" "}
                    {r.run.vram_gb ?? "?"} GB · <Trust t={r.run.trust_tier} />
                    {r.run.submitter ? (
                      <span className="text-stone-500"> · @{r.run.submitter}</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-stone-600">
            {data.count} model{data.count === 1 ? "" : "s"}
            {vram ? ` with a run that fits ≤${vram} GB VRAM` : ""}.
          </p>
        </div>
      )}
    </main>
  );
}

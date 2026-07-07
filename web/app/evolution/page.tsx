import { getLeaderboard } from "@/lib/api";
import { ApiDown } from "@/components/ui";
import EvolutionChart, { type Point } from "./EvolutionChart";

export const dynamic = "force-dynamic";
export const metadata = { title: "Capability evolution — Peakstone" };

export default async function EvolutionPage() {
  const res = await getLeaderboard({});
  const data = res.ok ? res.data : null;
  const points: Point[] = (data?.leaderboard ?? [])
    // ranked rows only: the frontier chart is a claim about the field, so it plots verified
    // (runner/community-verified) runs — a self-signed bundle with forged dates never lands here
    .filter((r) => r.held_out_status === "ranked")
    .filter((r) => r.release_date && r.held_out_score != null)
    .map((r) => ({
      family: r.family,
      date: Date.parse(r.release_date as string),
      dateLabel: r.release_date as string,
      score: r.held_out_score as number,
      vram: r.run.vram_gb,
      clean: r.held_out?.n_clean,
    }))
    .filter((p) => !Number.isNaN(p.date));

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Capability evolution</h1>
      <p className="mt-1 max-w-2xl text-sm text-stone-400">
        Each model&apos;s <strong>held-out</strong> code score against its release date — scored only
        on challenges <em>published after the model shipped</em>, which it could not have trained on.
        This is the honest frontier: contaminated (pre-release) challenges are excluded, so the line
        reflects generalization, not memorization. Hover a point for its held-out sample size.
      </p>

      <div className="mt-6">
        {!data ? (
          <ApiDown />
        ) : points.length === 0 ? (
          <p className="text-sm text-stone-400">
            No held-out runs yet. A point appears once a model has a known <code>release_date</code>
            {" "}and at least one scored challenge published after it.
          </p>
        ) : (
          <EvolutionChart points={points} />
        )}
      </div>
    </main>
  );
}

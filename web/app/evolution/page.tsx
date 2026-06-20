import { getLeaderboard } from "@/lib/api";
import { ApiDown } from "@/components/ui";
import EvolutionChart, { type Point } from "./EvolutionChart";

export const dynamic = "force-dynamic";
export const metadata = { title: "Capability evolution — Peakstone" };

export default async function EvolutionPage() {
  const data = await getLeaderboard({});
  const points: Point[] = (data?.leaderboard ?? [])
    .filter((r) => r.release_date && r.code_score != null)
    .map((r) => ({
      family: r.family,
      date: Date.parse(r.release_date as string),
      dateLabel: r.release_date as string,
      score: r.code_score as number,
      vram: r.run.vram_gb,
    }))
    .filter((p) => !Number.isNaN(p.date));

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Capability evolution</h1>
      <p className="mt-1 max-w-2xl text-sm text-stone-400">
        Each model&apos;s best code score against its release date — the rising high-water mark of
        open-model coding. The frontier moves up as new models land; saturated challenges drop to the
        floor.
      </p>

      <div className="mt-6">
        {!data ? (
          <ApiDown />
        ) : points.length === 0 ? (
          <p className="text-sm text-stone-400">
            No dated runs yet. The chart fills in as models with known release dates are submitted.
          </p>
        ) : (
          <EvolutionChart points={points} />
        )}
      </div>
    </main>
  );
}

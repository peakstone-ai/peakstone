import Link from "next/link";
import { getChallenges } from "@/lib/api";
import { ApiDown } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Challenges — Peakstone" };

function PassRate({ r }: { r: number | null }) {
  if (r == null) return <span className="text-stone-600">—</span>;
  // empirical difficulty: low pass-rate = hard (the calibrated tier, not the seed guess)
  const pct = Math.round(r * 100);
  const tone = r >= 0.8 ? "text-emerald-400" : r >= 0.4 ? "text-amber-400" : "text-rose-400";
  return <span className={`tabular-nums ${tone}`}>{pct}%</span>;
}

export default async function ChallengesPage() {
  const data = await getChallenges();
  if (!data) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  // hardest first (lowest pass-rate); unrun challenges sink to the bottom
  const rows = [...data.challenges].sort(
    (a, b) => (a.pass_rate ?? 2) - (b.pass_rate ?? 2)
  );

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Challenges</h1>
      <p className="mt-1 max-w-2xl text-sm text-stone-400">
        The verifiable corpus. <em>Pass-rate</em> is the empirical difficulty — the share of runs that
        fully solved it. As models improve, a challenge&apos;s pass-rate climbs and it drifts down the
        difficulty tiers; that drift is the capability story.
      </p>

      {rows.length === 0 ? (
        <p className="mt-6 text-stone-400">No challenges recorded yet.</p>
      ) : (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-stone-500">
                <th className="py-2 pr-4 font-medium">Challenge</th>
                <th className="py-2 pr-4 font-medium">Category</th>
                <th className="py-2 pr-4 font-medium">Verification</th>
                <th className="py-2 pr-4 font-medium">Seed tier</th>
                <th className="py-2 pr-4 font-medium">Pass-rate</th>
                <th className="py-2 pr-4 font-medium">Avg score</th>
                <th className="py-2 pr-4 font-medium">Runs</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((ch) => (
                <tr key={ch.id} className="border-t border-stone-800">
                  <td className="py-2 pr-4">
                    <Link
                      href={`/challenges/${encodeURIComponent(ch.id)}`}
                      className="font-medium text-stone-100 hover:text-emerald-400"
                    >
                      {ch.id}
                    </Link>
                  </td>
                  <td className="py-2 pr-4 text-stone-400">{ch.category ?? "—"}</td>
                  <td className="py-2 pr-4 text-stone-500">{ch.verification ?? "—"}</td>
                  <td className="py-2 pr-4 tabular-nums text-stone-400">
                    {ch.seed_difficulty ?? "—"}
                  </td>
                  <td className="py-2 pr-4">
                    <PassRate r={ch.pass_rate} />
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {ch.avg_score == null ? "—" : ch.avg_score.toFixed(3)}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-500">{ch.n_runs}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-stone-600">{data.count} challenges.</p>
        </div>
      )}
    </main>
  );
}

import Link from "next/link";
import { notFound } from "next/navigation";
import { getChallenge } from "@/lib/api";
import { ApiDown, DataTable, ScoreBar, Trust } from "@/components/ui";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return { title: `${decodeURIComponent(id)} — Peakstone` };
}

export default async function ChallengePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const res = await getChallenge(decodeURIComponent(id));
  if (!res.ok) {
    if (res.notFound) notFound(); // unknown challenge id → a real 404 (R23)
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  const data = res.data;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/challenges" className="text-sm text-stone-500 hover:text-stone-300">
        ← challenges
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">{data.id}</h1>
      <p className="mt-1 text-sm text-stone-400">
        {data.category ? `${data.category} · ` : ""}
        {data.verification ?? "deterministic-tests"}
        {data.seed_difficulty != null ? ` · seed tier ${data.seed_difficulty}` : ""} · {data.status}
      </p>

      <h2 className="mt-6 text-lg font-medium">Best result per model</h2>
      {data.results.length === 0 ? (
        <p className="mt-2 text-sm text-stone-400">No runs have attempted this challenge yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <DataTable head={["#", "Model", "Score", "Tests", "Run"]}>
            {data.results.map((r, i) => (
                <tr key={r.family} className="border-t border-stone-800">
                  <td className="py-2 pr-2 tabular-nums text-stone-500">{i + 1}</td>
                  <td className="py-2 pr-4">
                    <Link
                      href={`/models/${encodeURIComponent(r.family)}`}
                      className="font-medium text-stone-100 hover:text-emerald-400"
                    >
                      {r.family}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">
                    <ScoreBar v={r.score} />
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-400">
                    {r.passed == null || r.total == null ? "—" : `${r.passed}/${r.total}`}
                  </td>
                  <td className="py-2 pr-4 text-stone-400">
                    {r.run.artifact} · {r.run.vram_gb ?? "?"} GB · <Trust t={r.run.trust_tier} />
                  </td>
                </tr>
            ))}
          </DataTable>
          <p className="mt-3 text-xs text-stone-600">{data.n_families} models attempted.</p>
        </div>
      )}
    </main>
  );
}

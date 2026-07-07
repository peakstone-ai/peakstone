import { getChallenges } from "@/lib/api";
import { ApiDown } from "@/components/ui";
import ChallengesTable from "./ChallengesTable";

export const dynamic = "force-dynamic";
export const metadata = { title: "Challenges — Peakstone" };

export default async function ChallengesPage() {
  const res = await getChallenges();
  if (!res.ok) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  const data = res.data;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Challenges</h1>
      <p className="mt-1 max-w-2xl text-sm text-stone-400">
        The verifiable corpus: native challenges authored for Peakstone plus imported public
        benchmarks, each dated by when its content first became public (that date powers the
        held-out board). The official leaderboard runs a pinned, versioned selection of these —
        a <em>level</em> — so scores stay comparable.
      </p>
      <p className="mt-2 max-w-2xl text-sm text-stone-400">
        <em>Seed tier</em> is the author&apos;s difficulty guess (1–5) when the challenge entered
        the corpus. <em>Pass-rate</em> is the empirical difficulty — the share of runs that fully
        solved it. As models improve, a challenge&apos;s pass-rate climbs and it migrates down the
        tiers; that drift, challenge by challenge, is the capability story this page tells.
      </p>

      {data.challenges.length === 0 ? (
        <p className="mt-6 text-stone-400">No challenges recorded yet.</p>
      ) : (
        <>
          <ChallengesTable challenges={data.challenges} />
          <p className="mt-3 text-xs text-stone-600">{data.count} challenges.</p>
        </>
      )}
    </main>
  );
}

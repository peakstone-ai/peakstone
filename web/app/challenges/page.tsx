import { getChallenges } from "@/lib/api";
import { ApiDown } from "@/components/ui";
import ChallengesTable from "./ChallengesTable";

export const dynamic = "force-dynamic";
export const metadata = { title: "Challenges — Peakstone" };

export default async function ChallengesPage() {
  const data = await getChallenges();
  if (!data) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Challenges</h1>
      <p className="mt-1 max-w-2xl text-sm text-stone-400">
        The verifiable corpus. <em>Pass-rate</em> is the empirical difficulty — the share of runs that
        fully solved it. As models improve, a challenge&apos;s pass-rate climbs and it drifts down the
        difficulty tiers; that drift is the capability story.
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

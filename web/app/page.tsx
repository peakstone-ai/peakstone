import Link from "next/link";
import { getChallenges, getLeaderboard } from "@/lib/api";
import { ApiDown } from "@/components/ui";

export const dynamic = "force-dynamic";

// The prominent destination cards — the four places a visitor actually wants to go.
const DESTINATIONS: { href: string; title: string; blurb: string }[] = [
  {
    href: "/leaderboard",
    title: "Leaderboard",
    blurb: "Every model ranked by its held-out score — plus agentic, planner and safety lenses.",
  },
  {
    href: "/challenges",
    title: "Challenges",
    blurb: "The verifiable corpus, with empirical pass-rates as the difficulty signal.",
  },
  {
    href: "/submit",
    title: "Submit a run",
    blurb: "Benchmark a model on your own hardware and publish the signed bundle.",
  },
  {
    href: "/evolution",
    title: "Evolution",
    blurb: "The held-out capability frontier of open models over time.",
  },
];

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-stone-800 bg-stone-900/40 px-6 py-4 text-center">
      <div className="text-2xl font-semibold tabular-nums text-emerald-400">
        {value.toLocaleString("en-US")}
      </div>
      <div className="mt-0.5 text-xs uppercase tracking-wide text-stone-500">{label}</div>
    </div>
  );
}

export default async function Home() {
  // Cheap live stats; both fetchers return null when the API is unreachable.
  const [board, challenges] = await Promise.all([getLeaderboard({}), getChallenges()]);
  // total scored (run, challenge) results across the corpus
  const nResults = challenges?.challenges.reduce((n, ch) => n + ch.n_runs, 0) ?? 0;
  const apiUp = board !== null && challenges !== null;

  return (
    <main className="mx-auto max-w-3xl px-4 py-16">
      <section className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight text-stone-100">
          <span aria-hidden>🪨</span> Peakstone
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-stone-400">
          An open, verifiable LLM benchmark — <strong className="text-stone-200">signed result
          bundles</strong>, deterministic verification, and{" "}
          <strong className="text-stone-200">held-out scoring</strong> on challenges published after
          each model&apos;s release.
        </p>
      </section>

      <section className="mt-10">
        {!apiUp ? (
          <ApiDown />
        ) : (
          <div className="grid grid-cols-3 gap-4">
            <Stat label="Models ranked" value={board.count} />
            <Stat label="Challenges" value={challenges.count} />
            <Stat label="Scored results" value={nResults} />
          </div>
        )}
      </section>

      <section className="mt-10 grid gap-4 sm:grid-cols-2">
        {DESTINATIONS.map((d) => (
          <Link
            key={d.href}
            href={d.href}
            className="group rounded-lg border border-stone-800 bg-stone-900/40 p-5 transition-colors hover:border-emerald-700"
          >
            <h2 className="font-medium text-stone-100 group-hover:text-emerald-400">
              {d.title} <span aria-hidden>→</span>
            </h2>
            <p className="mt-1 text-sm text-stone-400">{d.blurb}</p>
          </Link>
        ))}
      </section>

      <p className="mt-10 text-center text-sm text-stone-500">
        Reproducible and community-run —{" "}
        <a
          href="https://pypi.org/project/peakstone/"
          target="_blank"
          rel="noreferrer"
          className="text-emerald-400 hover:underline"
        >
          PyPI ↗
        </a>{" "}
        ·{" "}
        <a
          href="https://github.com/peakstone-ai/peakstone"
          target="_blank"
          rel="noreferrer"
          className="text-emerald-400 hover:underline"
        >
          GitHub ↗
        </a>
      </p>
    </main>
  );
}

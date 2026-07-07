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
  // Cheap live stats; render the graceful card when the API is unreachable.
  const [boardRes, challengesRes] = await Promise.all([getLeaderboard({}), getChallenges()]);
  const board = boardRes.ok ? boardRes.data : null;
  const challenges = challengesRes.ok ? challengesRes.data : null;
  // verified numbers only: "Models ranked" counts the ranked tier (not provisional claims), and
  // challenge n_runs is already trusted-runs-only server-side — a forged bundle moves nothing here
  const nRanked =
    board?.leaderboard.filter((r) => r.held_out_status === "ranked").length ?? 0;
  const nResults = challenges?.challenges.reduce((n, ch) => n + ch.n_runs, 0) ?? 0;
  // the number no other leaderboard can even display: independent re-runs of exact result vectors
  const nReproductions =
    board?.leaderboard.reduce((n, r) => n + (r.run.reproductions || 0), 0) ?? 0;
  const apiUp = board !== null && challenges !== null;

  return (
    <main className="mx-auto max-w-4xl px-4 py-12">
      <Hero />

      <section className="mt-10">
        {!apiUp ? (
          <ApiDown />
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Models ranked" value={nRanked} />
            <Stat label="Challenges" value={challenges.count} />
            <Stat label="Scored results" value={nResults} />
            <Stat label="Independent reproductions" value={nReproductions} />
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

      <div className="mt-12">
        <GettingStarted />
      </div>
    </main>
  );
}

function Hero() {
  return (
    <section className="text-center">
      <h1 className="text-3xl font-semibold tracking-tight text-stone-100">
        The leaderboard you don&apos;t have to trust
      </h1>
      <p className="mx-auto mt-3 max-w-2xl text-stone-400">
        A benchmark score you can&apos;t re-run is a press release. Peakstone ranks open &amp; local
        models on coding, math, agentic and safety tasks by their <em>held-out</em> score — only
        challenges published <em>after</em> a model&apos;s release, so it couldn&apos;t have trained
        on them — and every result is a{" "}
        <strong className="text-stone-200">signed, content-addressed run</strong>. Reproduce one on
        your own GPU and it counts toward the{" "}
        <strong className="text-stone-200">community-verified tier — the tier that ranks</strong>.
      </p>
      <div className="mx-auto mt-6 w-full max-w-md text-left">
        <Terminal />
      </div>
      <p className="mx-auto mt-4 max-w-xl text-sm text-stone-400">
        <strong className="text-stone-200">Run it on your own hardware.</strong> The dashboard shows
        the board filtered to models that fit <em>your</em> GPU, serves and reproduces any run, then
        lets you submit your own signed results.
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-x-5 gap-y-1">
        <a href="https://pypi.org/project/peakstone/" target="_blank" rel="noreferrer"
           className="text-emerald-400 hover:underline">PyPI ↗</a>
        <a href="https://github.com/peakstone-ai/peakstone" target="_blank" rel="noreferrer"
           className="text-emerald-400 hover:underline">GitHub ↗</a>
      </div>
    </section>
  );
}

function Terminal() {
  return (
    <div className="overflow-hidden rounded-lg border border-stone-800 bg-black shadow-lg shadow-black/40">
      <div className="flex items-center gap-1.5 border-b border-stone-800 bg-stone-900/80 px-3 py-2">
        <span className="h-3 w-3 rounded-full bg-red-500/70" />
        <span className="h-3 w-3 rounded-full bg-yellow-500/70" />
        <span className="h-3 w-3 rounded-full bg-green-500/70" />
        <span className="ml-2 text-xs text-stone-500">bash</span>
      </div>
      <div className="px-4 py-4 font-mono text-sm">
        <span className="text-emerald-400">${" "}</span>
        <span className="term-type text-stone-100">pipx install peakstone</span>
      </div>
    </div>
  );
}

function StepCard({ n, title, cmd, shell = true, children }: {
  n: string; title: string; cmd: string; shell?: boolean; children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-stone-800 bg-stone-900/40 p-4 text-left">
      <div className="text-xs font-medium uppercase tracking-wide text-emerald-400">{n}</div>
      <h3 className="mt-1 font-medium text-stone-100">{title}</h3>
      <code className="mt-2 block rounded bg-black px-2 py-1 font-mono text-xs text-stone-200">
        {shell ? <span className="text-emerald-400">$ </span> : null}{cmd}
      </code>
      <p className="mt-2 text-sm text-stone-400">{children}</p>
    </div>
  );
}

function GettingStarted() {
  const snippet = `from openai import OpenAI

client = OpenAI(base_url="http://localhost:12434/v1", api_key="local")
client.chat.completions.create(          # the model field picks which local
    model="qwen3-coder",                 # model to load — the gateway swaps it in
    messages=[{"role": "user", "content": "refactor this function..."}],
)`;
  return (
    <section className="border-t border-stone-800 pt-8 text-center">
      <h2 className="text-lg font-semibold text-stone-200">Once installed</h2>
      <p className="mx-auto mt-1 max-w-2xl text-sm text-stone-400">
        Peakstone isn&apos;t just a leaderboard — it&apos;s a full local stack: a hardware dashboard, a
        model-swapping OpenAI gateway, and a browser chat UI.
      </p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <StepCard n="Step 1" title="Launch the dashboard" cmd="peakstone">
          The terminal UI: the leaderboard filtered to <em>your</em> GPU, browse &amp; download models,
          run the benchmark, and keep a wishlist of models to test.
        </StepCard>
        <StepCard n="Step 2" title="Chat with your models" cmd="peakstone serve">
          Starts a local gateway that loads models on demand, then open the built-in chat UI at{" "}
          <a href="http://localhost:12434/chat" className="text-emerald-400 hover:underline">
            localhost:12434/chat
          </a>.
        </StepCard>
        <StepCard n="Step 3" title="Use the OpenAI API" cmd="http://localhost:12434/v1" shell={false}>
          Point any OpenAI-compatible app or SDK at it. The <code>model</code> field selects which
          local model to serve — no per-model servers to manage.
        </StepCard>
      </div>
      <details className="mt-4 text-left">
        <summary className="cursor-pointer text-sm font-medium text-stone-300 hover:text-stone-100">
          Drop-in OpenAI example
        </summary>
        <pre className="mt-2 overflow-x-auto rounded-lg border border-stone-800 bg-black p-4 font-mono text-xs leading-relaxed text-stone-200">
          {snippet}
        </pre>
      </details>
    </section>
  );
}

import Link from "next/link";
import { notFound } from "next/navigation";
import { getRunChallenge, getChallengeSource } from "@/lib/api";
import { ApiDown, ScoreBar } from "@/components/ui";

export const dynamic = "force-dynamic";

function Code({ text }: { text: string }) {
  return (
    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-stone-900 p-3 text-xs leading-relaxed text-stone-200">
      {text}
    </pre>
  );
}

// A plain section (always open) or a collapsible one for long/secondary content.
function Section({
  title,
  text,
  collapsible = false,
}: {
  title: string;
  text?: string;
  collapsible?: boolean;
}) {
  if (!text) return null;
  if (collapsible) {
    return (
      <details className="mt-5">
        <summary className="cursor-pointer text-sm font-medium text-stone-300 hover:text-stone-100">
          {title}
        </summary>
        <Code text={text} />
      </details>
    );
  }
  return (
    <section className="mt-5">
      <h2 className="text-sm font-medium text-stone-300">{title}</h2>
      <Code text={text} />
    </section>
  );
}

export default async function SolutionPage({
  params,
}: {
  params: Promise<{ hash: string; challenge: string }>;
}) {
  const { hash, challenge } = await params;
  const [res, sourceRes] = await Promise.all([
    getRunChallenge(decodeURIComponent(hash), decodeURIComponent(challenge)),
    getChallengeSource(decodeURIComponent(challenge)),
  ]);
  if (!res.ok) {
    if (res.notFound) notFound(); // unknown run/challenge → a real 404 (R23)
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  const data = res.data;
  // a source 404 is EXPECTED content (non-public corpus), not an error — render the explainer
  const source = sourceRes.ok ? sourceRes.data : null;
  const t = data.transcript;
  const attempts = t?.attempts && t.attempts.length ? JSON.stringify(t.attempts, null, 2) : undefined;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <Link
        href={`/runs/${encodeURIComponent(hash)}`}
        className="text-sm text-stone-500 hover:text-stone-300"
      >
        ← run
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">{data.challenge}</h1>
      <div className="mt-2 flex items-center gap-3 text-sm text-stone-400">
        <div className="w-40">
          <ScoreBar v={data.final} />
        </div>
        {data.total ? <span className="tabular-nums">{data.passed ?? 0}/{data.total} tests</span> : null}
        {data.category ? <span>· {data.category}</span> : null}
      </div>

      {!t ? (
        <p className="mt-6 text-sm text-stone-400">
          No transcript was captured for this challenge (e.g. a reference run, or an error before generation).
        </p>
      ) : (
        <>
          {/* reading order: the challenge, then how the model was instructed, then what it produced */}
          <details className="mt-5">
            <summary className="cursor-pointer text-sm font-medium text-stone-300 hover:text-stone-100">
              Challenge{source?.difficulty ? ` · difficulty ${source.difficulty}/5` : ""}
            </summary>
            {source ? (
              <>
                {source.spec ? <Code text={source.spec} /> : null}
                {Object.entries(source.tests).map(([name, body]) => (
                  <div key={name} className="mt-2">
                    <div className="text-xs text-stone-500">tests/{name}</div>
                    <Code text={body} />
                  </div>
                ))}
              </>
            ) : (
              <p className="mt-1 text-sm text-stone-400">
                This challenge isn&apos;t in the public source (an external / opt-in benchmark), so its
                content isn&apos;t shown here.{" "}
                <Link
                  href={`/challenges/${encodeURIComponent(data.challenge)}`}
                  className="text-emerald-400 hover:underline"
                >
                  Open the {data.challenge} page →
                </Link>
              </p>
            )}
          </details>
          <Section title="System prompt" text={t.system_prompt} collapsible />
          <Section title="Proposed solution" text={t.raw_output} collapsible />
          <Section title="Plan" text={t.plan} />
          {t.stdout ? <Section title="Test output (stdout)" text={t.stdout} /> : null}
          {t.stderr ? <Section title="Errors (stderr)" text={t.stderr} /> : null}
          <Section title="Reasoning (chain-of-thought)" text={t.reasoning} collapsible />
          <Section title="Self-repair attempts" text={attempts} collapsible />
        </>
      )}
    </main>
  );
}

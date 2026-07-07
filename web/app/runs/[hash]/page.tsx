import Link from "next/link";
import { notFound } from "next/navigation";
import { getRun, getRunReproductions, type RunReproductions } from "@/lib/api";
import { ApiDown, CodeBlock, DataTable, ScoreBar, Trust } from "@/components/ui";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ hash: string }> }) {
  const { hash } = await params;
  return { title: `Run ${decodeURIComponent(hash).slice(0, 12)} — Peakstone` };
}

// The proof artifact: who independently re-ran this exact deterministic result vector — and the
// one-liner for becoming the next verifier. This section is the page to link when someone says
// "benchmarks are all contaminated anyway".
function Reproductions({ r, hash }: { r: RunReproductions; hash: string }) {
  return (
    <section className="mt-6 rounded-lg border border-stone-800 bg-stone-900/40 p-4">
      <h2 className="text-lg font-medium">
        Reproductions
        {r.distinct_identities > 0 ? (
          <span className="ml-2 rounded bg-emerald-700/60 px-1.5 py-0.5 text-xs text-emerald-200">
            ✓ ×{r.distinct_identities} independent
          </span>
        ) : (
          <span className="ml-2 rounded bg-stone-800 px-1.5 py-0.5 text-xs text-stone-400">
            unverified
          </span>
        )}
      </h2>
      {r.n === 0 ? (
        <p className="mt-2 text-sm text-stone-400">
          Nobody has independently re-run this result yet.{" "}
          <strong className="text-stone-200">Be the first to verify it</strong> — one command
          re-runs its deterministic challenges on your own GPU and compares, bit for bit:
        </p>
      ) : (
        <>
          <div className="mt-3 overflow-x-auto">
            <DataTable head={["Who", "Hardware", "When", "Run"]}>
              {r.reproductions.map((p) => (
                <tr key={p.bundle_hash} className="border-t border-stone-800">
                  <td className="py-2 pr-4 text-stone-300">
                    {p.submitter ? `@${p.submitter}` : "anonymous key"}
                    {p.independent ? null : (
                      <span className="ml-1 text-xs text-stone-500" title="the run's own submitter re-ran it — transparency, not verification">
                        (self)
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4 text-stone-400">
                    {p.gpu ?? "—"}{p.vram_gb ? ` · ${p.vram_gb} GB` : ""}
                  </td>
                  <td className="py-2 pr-4 text-stone-500">
                    {p.submitted_at ? p.submitted_at.slice(0, 10) : "—"}
                  </td>
                  <td className="py-2 pr-4">
                    <Link
                      href={`/runs/${encodeURIComponent(p.bundle_hash)}`}
                      className="text-xs text-stone-500 hover:text-emerald-400"
                    >
                      {p.bundle_hash.slice(0, 12)}
                    </Link>
                  </td>
                </tr>
              ))}
            </DataTable>
          </div>
          <p className="mt-3 text-sm text-stone-400">Add your own confirmation:</p>
        </>
      )}
      <CodeBlock text={`pipx install peakstone\npeakstone reproduce ${hash} --submit`} className="mt-2 text-sm" />
      <p className="mt-2 text-xs text-stone-500">
        A matching reproduction from enough distinct GitHub-bound accounts promotes the run to the
        community-verified (ranked) tier.
      </p>
    </section>
  );
}

export default async function RunPage({
  params,
}: {
  params: Promise<{ hash: string }>;
}) {
  const { hash } = await params;
  const [res, reproRes] = await Promise.all([
    getRun(decodeURIComponent(hash)),
    getRunReproductions(decodeURIComponent(hash)),
  ]);
  if (!res.ok) {
    if (res.notFound) notFound(); // unknown bundle hash → a real 404 (R23)
    return (
      <main className="mx-auto max-w-5xl px-4 py-8">
        <ApiDown />
      </main>
    );
  }
  const data = res.data;
  const repro = reproRes.ok ? reproRes.data : null;
  const short = data.bundle_hash.slice(0, 12);

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      {data.family ? (
        <Link
          href={`/models/${encodeURIComponent(data.family)}`}
          className="text-sm text-stone-500 hover:text-stone-300"
        >
          ← {data.family}
        </Link>
      ) : (
        <Link href="/leaderboard" className="text-sm text-stone-500 hover:text-stone-300">
          ← leaderboard
        </Link>
      )}
      <h1 className="mt-2 text-2xl font-semibold">
        {data.family ?? "Run"} {data.artifact ? <span className="text-stone-400">{data.artifact}</span> : null}
      </h1>
      <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-stone-400">
        <span>{data.n} challenge{data.n === 1 ? "" : "s"}</span>
        {data.context ? <span>· {Math.round(data.context / 1024)}K ctx</span> : null}
        <span>· {data.suite}</span>
        <span>· <Trust t={data.trust_tier} /></span>
        <span className="text-stone-600">· {short}</span>
      </p>

      {repro ? <Reproductions r={repro} hash={data.bundle_hash} /> : null}

      <p className="mt-4 text-sm text-stone-500">Select a challenge to see the model’s proposed solution.</p>
      <div className="mt-2 overflow-x-auto">
        <DataTable head={["Challenge", "Category", "Score", "Tests", "Note"]}>
          {data.results.map((r) => (
              <tr key={r.challenge} className="border-t border-stone-800 hover:bg-stone-900/40">
                <td className="py-2 pr-4">
                  <Link
                    href={`/runs/${encodeURIComponent(data.bundle_hash)}/${encodeURIComponent(r.challenge)}`}
                    className="font-medium text-stone-100 hover:text-emerald-400"
                  >
                    {r.challenge}
                  </Link>
                </td>
                <td className="py-2 pr-4 text-stone-400">{r.category ?? r.verification ?? "—"}</td>
                <td className="py-2 pr-4">
                  <ScoreBar v={r.final} />
                </td>
                <td className="py-2 pr-4 tabular-nums text-stone-400">
                  {r.total ? `${r.passed ?? 0}/${r.total}` : "—"}
                </td>
                <td className="py-2 pr-4 text-xs text-amber-400/80">{r.error ?? ""}</td>
              </tr>
          ))}
        </DataTable>
      </div>
    </main>
  );
}

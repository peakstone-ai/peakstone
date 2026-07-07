import { getProposals } from "@/lib/api";
import { ApiDown } from "@/components/ui";

export const dynamic = "force-dynamic";
export const metadata = { title: "Challenge proposals — Peakstone" };

function Code({ children }: { children: string }) {
  return (
    <pre className="my-2 overflow-x-auto rounded-lg border border-stone-800 bg-stone-900 p-3 text-sm text-stone-200">
      <code>{children}</code>
    </pre>
  );
}

function StatusBadge({ s }: { s: string }) {
  const c =
    s === "approved"
      ? "bg-emerald-700/60 text-emerald-200"
      : s === "rejected"
      ? "bg-rose-800/50 text-rose-200"
      : "bg-amber-700/50 text-amber-200";
  return <span className={`rounded px-1.5 py-0.5 text-xs ${c}`}>{s}</span>;
}

export default async function ProposalsPage() {
  const res = await getProposals("all");
  const data = res.ok ? res.data : null;

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Challenge proposals</h1>
      <p className="mt-1 max-w-2xl text-sm text-stone-400">
        The open corpus: anyone can propose a challenge. Proposals queue here for review; an admin
        canonizes approved ones into the suite. The API never runs the submitted code — authors
        validate the reference locally, and a reviewer re-runs it before approving.
      </p>

      <h2 className="mt-6 text-lg font-medium">Propose one</h2>
      <p className="text-sm text-stone-400">
        Author a challenge dir (<code>meta.toml</code>, <code>spec.md</code>, <code>tests/</code>,{" "}
        <code>reference/</code>), then build + submit a signed proposal:
      </p>
      <Code>{`python -m engine.propose challenges/python/15-my-challenge   # validates reference, signs
curl -X POST $PEAKSTONE_API/proposals -H 'content-type: application/json' --data @proposal.json`}</Code>

      <h2 className="mt-6 text-lg font-medium">Queue</h2>
      {!data ? (
        <ApiDown />
      ) : data.proposals.length === 0 ? (
        <p className="mt-2 text-sm text-stone-400">No proposals yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-stone-500">
                <th className="py-2 pr-4 font-medium">Slug</th>
                <th className="py-2 pr-4 font-medium">Lang</th>
                <th className="py-2 pr-4 font-medium">Difficulty</th>
                <th className="py-2 pr-4 font-medium">Reference</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Submitted</th>
              </tr>
            </thead>
            <tbody>
              {data.proposals.map((p) => (
                <tr key={p.id} className="border-t border-stone-800">
                  <td className="py-2 pr-4 text-stone-100">{p.slug}</td>
                  <td className="py-2 pr-4 text-stone-400">{p.language ?? "—"}</td>
                  <td className="py-2 pr-4 tabular-nums text-stone-400">{p.difficulty ?? "—"}</td>
                  <td className="py-2 pr-4 text-xs">
                    {p.reference_passes == null ? (
                      <span className="text-stone-600">—</span>
                    ) : p.reference_passes ? (
                      <span className="text-emerald-400">passes</span>
                    ) : (
                      <span className="text-rose-400">fails</span>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <StatusBadge s={p.status} />
                  </td>
                  <td className="py-2 pr-4 text-stone-500">{p.created_at.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-stone-600">{data.count} proposals.</p>
        </div>
      )}
    </main>
  );
}

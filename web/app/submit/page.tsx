import { PUBLIC_API } from "@/lib/api";
import { CodeBlock } from "@/components/ui";

export const metadata = { title: "Submit a run — Peakstone" };

function Code({ children }: { children: string }) {
  return <CodeBlock text={children} className="my-3 text-sm" />;
}

export default function SubmitPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-2xl font-semibold">Submit a run</h1>
      <p className="mt-2 text-sm text-stone-400">
        You run the open engine against your own model and submit a <strong>signed result
        bundle</strong>. Deterministic results are independently re-runnable, so the leaderboard is
        trustworthy without us hosting any GPUs.
      </p>

      <h2 className="mt-6 text-lg font-medium">1. Install the client + fetch the challenge corpus</h2>
      <Code>{`pipx install peakstone
peakstone corpus sync
peakstone login    # optional: attributes runs to your GitHub handle`}</Code>

      <h2 className="mt-6 text-lg font-medium">2. Run the official suite on your own hardware</h2>
      <p className="text-sm text-stone-400">
        The easiest path is the local daemon — it serves your model, runs the suite, and chains the
        judge pass automatically:
      </p>
      <Code>{`peakstone serve --detach
peakstone jobs add <model-name> --level standard
# -> results/job-<id>/bundle.json  (schema-valid, content-addressed, ed25519-signed)`}</Code>

      <h2 className="mt-6 text-lg font-medium">3. Submit the signed bundle</h2>
      <Code>{`peakstone submit results/job-<id>/bundle.json`}</Code>
      <p className="text-sm text-stone-400">
        Or let the daemon publish finished runs itself (opt-in:{" "}
        <code className="rounded bg-stone-800 px-1 text-stone-200">auto_submit = true</code> under{" "}
        <code className="rounded bg-stone-800 px-1 text-stone-200">[gateway]</code>). Raw HTTP works
        too — plain or xz-compressed JSON:
      </p>
      <Code>{`curl -X POST ${PUBLIC_API}/submissions \\
  -H 'content-type: application/json' \\
  --data @results/job-<id>/bundle.json`}</Code>

      <h2 className="mt-6 text-lg font-medium">What gets recorded</h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-stone-400">
        <li>Exact model identity — HF repo + revision, file SHA-256, quant, engine version.</li>
        <li>Sampling + serve flags + the hardware/driver it ran on (the VRAM facet).</li>
        <li>Per-challenge content hashes, transcripts, and scores.</li>
      </ul>
      <p className="mt-3 text-sm text-stone-400">
        The whole bundle is content-addressed and signed by your key — the signature is your root
        identity. Link that key to GitHub with{" "}
        <code className="rounded bg-stone-800 px-1 text-stone-200">peakstone login</code>: optional,
        but it attributes runs to your handle and lets your reproductions count toward the
        community-verified (ranked) tier.
      </p>
    </main>
  );
}

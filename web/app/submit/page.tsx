import { API } from "@/lib/api";

export const metadata = { title: "Submit a run — Peakstone" };

function Code({ children }: { children: string }) {
  return (
    <pre className="my-3 overflow-x-auto rounded-lg border border-stone-800 bg-stone-900 p-3 text-sm text-stone-200">
      <code>{children}</code>
    </pre>
  );
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

      <h2 className="mt-6 text-lg font-medium">1. Serve a model</h2>
      <p className="text-sm text-stone-400">Any OpenAI-compatible endpoint works. For local GGUFs:</p>
      <Code>{`./serve/serve.sh <model-name>`}</Code>

      <h2 className="mt-6 text-lg font-medium">2. Run the suite and produce a bundle</h2>
      <Code>{`python -m engine.runner --models <model-name> --bundle
# -> results/<stamp>/bundle.json  (schema-valid, content-addressed, ed25519-signed)`}</Code>

      <h2 className="mt-6 text-lg font-medium">3. Submit it</h2>
      <Code>{`curl -X POST ${API}/submissions \\
  -H 'content-type: application/json' \\
  --data @results/<stamp>/bundle.json`}</Code>

      <h2 className="mt-6 text-lg font-medium">What gets recorded</h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-stone-400">
        <li>Exact model identity — HF repo + revision, file SHA-256, quant, engine version.</li>
        <li>Sampling + serve flags + the hardware/driver it ran on (the VRAM facet).</li>
        <li>Per-challenge content hashes, transcripts, and scores.</li>
      </ul>
      <p className="mt-3 text-sm text-stone-400">
        The whole bundle is content-addressed and signed by your key — the signature is the root
        identity; linking it to a handle/account (GitHub, …) comes later and is optional.
      </p>
    </main>
  );
}

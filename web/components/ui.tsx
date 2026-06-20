import { API } from "@/lib/api";

export function ScoreBar({ v }: { v: number | null }) {
  const pct = Math.round((v ?? 0) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded bg-stone-800">
        <div className="h-full rounded bg-emerald-500" style={{ width: `${pct}%` }} />
      </div>
      <span className="tabular-nums text-stone-200">{v == null ? "—" : v.toFixed(3)}</span>
    </div>
  );
}

export function Trust({ t }: { t: string }) {
  const c =
    t === "runner-verified"
      ? "bg-emerald-700/60 text-emerald-200"
      : t === "community-verified"
      ? "bg-sky-700/60 text-sky-200"
      : "bg-stone-700/60 text-stone-300";
  return <span className={`rounded px-1.5 py-0.5 text-xs ${c}`}>{t.replace(/-/g, " ")}</span>;
}

export function ApiDown() {
  return (
    <div className="rounded-lg border border-amber-800 bg-amber-950/40 p-4 text-sm text-amber-200">
      Can&apos;t reach the Peakstone API at <code className="text-amber-100">{API}</code>. Start it
      with <code className="text-amber-100">uvicorn api.main:app</code> (set{" "}
      <code>NEXT_PUBLIC_API_URL</code> to point elsewhere).
    </div>
  );
}

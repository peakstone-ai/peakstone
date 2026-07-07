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
  // No internal endpoint or operator instructions here — this renders to the public (review R16).
  return (
    <div className="rounded-lg border border-amber-800 bg-amber-950/40 p-4 text-sm text-amber-200">
      The Peakstone API is unreachable right now — live data will be back shortly. Refresh in a
      minute; if you run this site, check the API service logs.
    </div>
  );
}

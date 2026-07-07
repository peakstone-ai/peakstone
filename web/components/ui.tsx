export function ScoreBar({ v }: { v: number | null }) {
  // clamp: scores are 0..1 by contract, but a bad row must not draw a 300%-wide bar (review R27)
  const pct = Math.round(Math.min(1, Math.max(0, v ?? 0)) * 100);
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

// The ONE preformatted-code block (review R27 — it was declared three times, drifting): prose-ish
// commands (submit/proposals) and transcript panes (solution viewer) share it; `wrap` opts into
// soft-wrapping for long prose-like content, `text-*` size comes via className.
export function CodeBlock({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  return (
    <pre
      className={`overflow-x-auto rounded-lg border border-stone-800 bg-stone-900 p-3 text-stone-200 ${className}`}
    >
      <code>{text}</code>
    </pre>
  );
}

// Shared table chrome (review R27 — the same three classNames were hand-copied per page). Header
// cells accept a plain label or {label, title} for a hover explanation.
export type Head = string | { label: string; title?: string };

export function DataTable({ head, children }: { head: Head[]; children: React.ReactNode }) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="text-left text-stone-500">
          {head.map((h) => {
            const label = typeof h === "string" ? h : h.label;
            const title = typeof h === "string" ? undefined : h.title;
            return (
              <th key={label} className="py-2 pr-4 font-medium" title={title}>
                {label}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

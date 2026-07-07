import { Fragment } from "react";
import Link from "next/link";
import type { LeaderRow } from "@/lib/api";
import { ScoreBar, Trust } from "@/components/ui";

// served thinking budget: 0=off, -1=full, N=capped at N tokens
export function budgetLabel(n: number): string {
  if (n === 0) return "off";
  if (n < 0) return "full";
  return `${Math.round(n / 1024)}k cap`;
}

// the thinking run-condition badge text: prefer the served budget, fall back to the on/off evidence
function thinkLabel(reasoning: string | null, budget: number | null): string | null {
  if (budget != null) return budgetLabel(budget);
  return reasoning;
}

// compact efficiency axes shown in the leaderboard (matches engine/metrics.py)
const METRIC_COLS: { key: string; fmt: (v: number) => string }[] = [
  { key: "loc", fmt: (v) => `${Math.round(v)} LOC` },
  { key: "peak_rss_mb", fmt: (v) => `${Math.round(v)} MB` },
  { key: "test_wall_s", fmt: (v) => `${v.toFixed(1)}s` },
];

export default function BoardTable({
  rows,
  isHeldOut,
  sort,
  count,
  vram,
}: {
  rows: LeaderRow[];
  isHeldOut: boolean;
  sort: string;
  count: number;
  vram: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-stone-500">
            <th className="py-2 pr-2 font-medium">#</th>
            <th className="py-2 pr-4 font-medium">Model</th>
            <th className="py-2 pr-4 font-medium">Held-out</th>
            <th className="py-2 pr-4 font-medium" title="distinct accounts that independently re-ran this exact result vector (peakstone reproduce <hash>)">Verified</th>
            <th className="py-2 pr-4 font-medium">All-corpus</th>
            <th className="py-2 pr-4 font-medium">Math</th>
            <th className="py-2 pr-4 font-medium">Agentic</th>
            <th className="py-2 pr-4 font-medium">Planner</th>
            <th className="py-2 pr-4 font-medium">Safety</th>
            <th className="py-2 pr-4 font-medium">Calibration</th>
            <th className="py-2 pr-4 font-medium">Self-repair</th>
            <th className="py-2 pr-4 font-medium" title="Fraction of generations cut off at the token budget — lower is better. A high rate means scores are budget-limited, not capability-limited.">Truncation</th>
            <th className="py-2 pr-4 font-medium">Solved</th>
            <th className="py-2 pr-4 font-medium">Efficiency</th>
            <th className="py-2 pr-4 font-medium" title="the exact artifact (quant build) behind this row — every config ranks as its own run">Best run</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const showDivider =
              isHeldOut &&
              r.held_out_status === "provisional" &&
              (i === 0 || rows[i - 1].held_out_status !== "provisional");
            return (
              <Fragment key={r.family}>
                {showDivider && (
                  <tr>
                    <td
                      colSpan={15}
                      className="border-t border-stone-700 pt-3 pb-1 text-xs text-stone-500"
                    >
                      Provisional — not enough held-out challenges yet (newest first; claimed
                      scores are never used for ordering)
                    </td>
                  </tr>
                )}
                <tr className="border-t border-stone-800">
                  <td className="py-2 pr-2 tabular-nums text-stone-500">{r.rank}</td>
                  <td className="py-2 pr-4">
                    <Link
                      href={`/models/${encodeURIComponent(r.family)}`}
                      className="font-medium text-stone-100 hover:text-emerald-400"
                    >
                      {r.family}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">
                    {r.held_out_score == null ? (
                      <span className="text-stone-600" title="no release date or no post-release challenges yet">
                        —
                      </span>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        <ScoreBar v={r.held_out_score} />
                        <span className="text-xs text-stone-500">
                          {r.held_out.n_clean} clean · {Math.round(r.held_out.coverage * 100)}% dated
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    {r.run.reproductions > 0 ? (
                      <Link
                        href={`/runs/${encodeURIComponent(r.run.bundle_hash)}`}
                        className="rounded bg-emerald-700/60 px-1.5 py-0.5 text-xs text-emerald-200 hover:bg-emerald-700"
                        title={`independently reproduced by ${r.run.reproductions} distinct account${r.run.reproductions === 1 ? "" : "s"}`}
                      >
                        ✓ ×{r.run.reproductions}
                      </Link>
                    ) : (
                      <Link
                        href={`/runs/${encodeURIComponent(r.run.bundle_hash)}`}
                        className="text-xs text-stone-600 hover:text-emerald-400"
                        title={`no independent reproduction yet — be the first: peakstone reproduce ${r.run.bundle_hash.slice(0, 12)}…`}
                      >
                        unverified
                      </Link>
                    )}
                  </td>
                  <td className="py-2 pr-4">
                    <ScoreBar v={r.code_score} />
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.math_score == null ? "—" : `${r.math_score.toFixed(2)} (${r.n_math})`}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.agent_score == null ? "—" : `${r.agent_score.toFixed(2)} (${r.n_agent})`}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.planner_score == null ? "—" : `${r.planner_score.toFixed(2)} (${r.n_planner})`}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.safety_score == null ? "—" : r.safety_score.toFixed(2)}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.self_verify_accuracy == null ? (
                      "—"
                    ) : (
                      <span title={`confidence ${r.confidence_score ?? "—"} · ${r.n_calibration} probed`}>
                        {r.self_verify_accuracy.toFixed(2)}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.recovery_rate == null ? (
                      "—"
                    ) : (
                      <span title={`${r.n_repair} first-try failures retried`}>
                        {r.recovery_rate.toFixed(2)}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4 tabular-nums">
                    {r.truncation_rate == null ? (
                      <span className="text-stone-300">—</span>
                    ) : (
                      <span
                        title={`${r.n_generated} generated challenges${r.truncation_rate >= 0.1 ? " — budget may be too tight to fairly score this model" : ""}`}
                        className={r.truncation_rate >= 0.1 ? "text-amber-400" : "text-stone-300"}
                      >
                        {r.truncation_rate > 0 ? "✂ " : ""}
                        {r.truncation_rate.toFixed(2)}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-stone-300">
                    {r.solved}/{r.n_code}
                    {r.n_committed > 0 && (
                      <span
                        className="ml-1 text-xs text-stone-500"
                        title={`commit-and-reveal: ${r.n_committed} sealed private result(s), ${r.n_revealed} revealed. Sealed claims earn no credit until revealed — the committed/revealed ratio keeps selective reveal visible.`}
                      >
                        🔒{r.n_revealed}/{r.n_committed}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-4 text-xs tabular-nums text-stone-400">
                    {METRIC_COLS.filter((m) => r.metrics?.[m.key] != null).length === 0
                      ? "—"
                      : METRIC_COLS.filter((m) => r.metrics?.[m.key] != null).map((m) => (
                          <span
                            key={m.key}
                            className={`mr-2 ${sort === m.key ? "text-emerald-400" : ""}`}
                          >
                            {m.fmt(r.metrics[m.key])}
                          </span>
                        ))}
                  </td>
                  <td className="py-2 pr-4 text-stone-400">
                    <span className="text-stone-300">{r.run.artifact}</span> ·{" "}
                    {r.run.vram_gb ?? "?"} GB · <Trust t={r.run.trust_tier} />
                    {thinkLabel(r.run.reasoning, r.run.reasoning_budget) ? (
                      <span className="rounded bg-violet-900/50 px-1.5 py-0.5 text-xs text-violet-200">
                        {" "}think {thinkLabel(r.run.reasoning, r.run.reasoning_budget)}
                      </span>
                    ) : null}
                    {r.run.run_status === "not_capable" ? (
                      <span
                        className="rounded bg-red-900/50 px-1.5 py-0.5 text-xs text-red-200"
                        title={`not capable — repetition loops, abandoned: ${(r.run.abandoned_categories ?? []).join(", ") || "every category"}`}
                      >
                        {" "}not capable
                      </span>
                    ) : null}
                    {r.run.submitter ? (
                      <span className="text-stone-500"> · @{r.run.submitter}</span>
                    ) : null}
                  </td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-stone-600">
        {count} model{count === 1 ? "" : "s"}
        {vram ? ` with a run that fits ≤${vram} GB VRAM` : ""}.
      </p>
    </div>
  );
}

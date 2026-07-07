import { Fragment } from "react";
import Link from "next/link";
import { getFacets, getLeaderboard } from "@/lib/api";
import { LEADERBOARD_PARAMS } from "@/lib/params";
import { ApiDown, ScoreBar, Trust } from "@/components/ui";
import { SelectFilter } from "@/components/Filters";

export const dynamic = "force-dynamic";
export const metadata = { title: "Leaderboard — Peakstone" };

const VRAM_PRESETS: [string, string][] = [
  ["All", ""],
  ["≤8 GB", "8"],
  ["≤12 GB", "12"],
  ["≤16 GB", "16"],
  ["≤24 GB", "24"],
  ["≤48 GB", "48"],
];

// served thinking budget: 0=off, -1=full, N=capped at N tokens
function budgetLabel(n: number): string {
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

export default async function LeaderboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const vram = sp.max_vram_gb ?? "";
  const sort = sp.sort ?? "held_out_score";
  const isAgent = sort === "agent_score";
  const isPlanner = sort === "planner_score";
  const isAllCorpus = sort === "code_score";
  const isHeldOut = !isAgent && !isPlanner && !isAllCorpus;  // the default lens
  const boardTitle = isAgent
    ? "Agentic leaderboard"
    : isPlanner
    ? "Planner leaderboard"
    : isAllCorpus
    ? "Coder leaderboard (all challenges)"
    : "Leaderboard";
  const [boardRes, facetsRes] = await Promise.all([getLeaderboard(sp), getFacets()]);
  const data = boardRes.ok ? boardRes.data : null;
  const facets = facetsRes.ok ? facetsRes.data : null;

  return (
    <main className="mx-auto max-w-[1600px] px-4 py-8">
      <h2 className="text-center text-2xl font-semibold">{boardTitle}</h2>
      <p className="mx-auto mt-1 max-w-2xl text-center text-sm text-stone-400">
        {isPlanner ? (
          <>
            The best <em>planner</em> run per family — the model writes an implementation plan, a
            fixed coder executes it, and tests verify. The same coder for everyone isolates planning
            ability from coding.
          </>
        ) : isAgent ? (
          <>
            The best <em>agentic</em> run per family — multi-machine / goal-state-env tasks where the
            model drives an environment to a goal state. Scored separately from coding ability.
          </>
        ) : isAllCorpus ? (
          <>
            The best run per family ranked over <em>all</em> challenges — including older public
            benchmarks a model may have trained on. The default{" "}
            <Link href="/leaderboard" className="text-emerald-400 hover:underline">held-out view</Link> excludes
            those. Runs are never collapsed — quants, contexts, and hardware are distinct.
          </>
        ) : (
          <>
            Each model ranked by its <em>held-out</em> score — only challenges published <em>after</em>{" "}
            the model&apos;s release, which it could not have trained on. Models without enough
            held-out evidence yet are listed as <em>provisional</em> below. Safety and agentic ability
            are scored separately.
          </>
        )}
      </p>

      <div className="my-5 flex flex-wrap items-center justify-center gap-2">
        <span className="text-sm text-stone-500">Fits my hardware:</span>
        {VRAM_PRESETS.map(([label, val]) => {
          const active = vram === val;
          // rebuild the link from the ONE param list (review R24 — a hand-copy here once dropped
          // `verdict`, so pill clicks silently cleared an active verdict filter)
          const params = new URLSearchParams();
          for (const k of LEADERBOARD_PARAMS) {
            if (k !== "max_vram_gb" && sp[k]) params.set(k, sp[k] as string);
          }
          if (val) params.set("max_vram_gb", val);
          const qs = params.toString();
          return (
            <Link
              key={label}
              href={qs ? `/leaderboard?${qs}` : "/leaderboard"}
              className={`rounded-full px-3 py-1 text-sm transition-colors ${
                active
                  ? "bg-emerald-600 text-white"
                  : "bg-stone-800 text-stone-300 hover:bg-stone-700"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </div>

      {facets && (
        <div className="mb-5 flex flex-wrap items-center justify-center gap-4">
          {facets.quants.length > 0 && (
            <SelectFilter param="quant" label="Quant" options={facets.quants} />
          )}
          {facets.trust_tiers.length > 1 && (
            <SelectFilter param="trust" label="Trust" options={facets.trust_tiers} allLabel="Any" />
          )}
          {facets.reasoning.length > 0 && (
            <SelectFilter param="reasoning" label="Reasoning" options={facets.reasoning} allLabel="Any" />
          )}
          {facets.reasoning_budgets.length > 1 && (
            <SelectFilter
              param="reasoning_budget"
              label="Thinking budget"
              allLabel="Any"
              options={facets.reasoning_budgets.map((n) => ({
                value: String(n),
                label: budgetLabel(n),
              }))}
            />
          )}
          {facets.sort_axes.length > 0 && (
            <SelectFilter
              param="sort"
              label="Rank by"
              allLabel="held-out (default)"
              options={facets.sort_axes.map((a) => a.key).filter((k) => k !== "held_out_score")}
            />
          )}
        </div>
      )}

      {!data ? (
        <ApiDown />
      ) : data.leaderboard.length === 0 ? (
        <p className="text-stone-400">
          No runs yet{vram ? ` that fit in ≤${vram} GB VRAM` : ""}.{" "}
          <Link href="/submit" className="text-emerald-400 hover:underline">
            Submit one
          </Link>
          .
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="text-left text-stone-500">
                <th className="py-2 pr-2 font-medium">#</th>
                <th className="py-2 pr-4 font-medium">Model</th>
                <th className="py-2 pr-4 font-medium">Held-out</th>
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
                <th className="py-2 pr-4 font-medium">Best run</th>
              </tr>
            </thead>
            <tbody>
              {data.leaderboard.map((r, i) => {
                const showDivider =
                  isHeldOut &&
                  r.held_out_status === "provisional" &&
                  (i === 0 || data.leaderboard[i - 1].held_out_status !== "provisional");
                return (
                  <Fragment key={r.family}>
                    {showDivider && (
                      <tr>
                        <td
                          colSpan={14}
                          className="border-t border-stone-700 pt-3 pb-1 text-xs text-stone-500"
                        >
                          Provisional — not enough held-out challenges yet (ranked by all-corpus score)
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
            {data.count} model{data.count === 1 ? "" : "s"}
            {vram ? ` with a run that fits ≤${vram} GB VRAM` : ""}.
          </p>
        </div>
      )}
    </main>
  );
}

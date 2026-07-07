import Link from "next/link";
import { getFacets, getLeaderboard } from "@/lib/api";
import { LEADERBOARD_PARAMS } from "@/lib/params";
import { ApiDown } from "@/components/ui";
import { SelectFilter } from "@/components/Filters";
import BoardTable, { budgetLabel } from "./BoardTable";

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
        <BoardTable
          rows={data.leaderboard}
          isHeldOut={isHeldOut}
          sort={sort}
          count={data.count}
          vram={vram}
        />
      )}
    </main>
  );
}


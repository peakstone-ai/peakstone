"use client";

import { useState } from "react";
import Link from "next/link";
import type { ChallengeRow } from "@/lib/api";

// Sortable columns: each maps a header label to the row field it orders by.
type SortKey =
  | "id"
  | "category"
  | "verification"
  | "seed_difficulty"
  | "pass_rate"
  | "avg_score"
  | "n_runs";

const COLUMNS: { key: SortKey; label: string; title?: string }[] = [
  { key: "id", label: "Challenge" },
  { key: "category", label: "Category" },
  { key: "verification", label: "Verification" },
  { key: "seed_difficulty", label: "Seed tier",
    title: "the author's 1–5 difficulty guess when the challenge entered the corpus" },
  { key: "pass_rate", label: "Pass-rate",
    title: "empirical difficulty: the share of runs that fully solved it — climbs as models improve" },
  { key: "avg_score", label: "Avg score" },
  { key: "n_runs", label: "Runs" },
];

// Null-safe comparator: nulls always sink to the bottom regardless of direction; strings compare
// case-insensitively, numbers numerically.
function compare(a: ChallengeRow, b: ChallengeRow, key: SortKey, dir: 1 | -1): number {
  const av = a[key];
  const bv = b[key];
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  const cmp =
    typeof av === "string" && typeof bv === "string"
      ? av.toLowerCase().localeCompare(bv.toLowerCase())
      : (av as number) - (bv as number);
  return cmp * dir;
}

function PassRate({ r }: { r: number | null }) {
  if (r == null) return <span className="text-stone-600">—</span>;
  // empirical difficulty: low pass-rate = hard (the calibrated tier, not the seed guess)
  const pct = Math.round(r * 100);
  const tone = r >= 0.8 ? "text-emerald-400" : r >= 0.4 ? "text-amber-400" : "text-rose-400";
  return <span className={`tabular-nums ${tone}`}>{pct}%</span>;
}

export default function ChallengesTable({ challenges }: { challenges: ChallengeRow[] }) {
  // default: hardest first (lowest pass-rate); unrun challenges sink to the bottom
  const [sortKey, setSortKey] = useState<SortKey>("pass_rate");
  const [dir, setDir] = useState<1 | -1>(1);

  function onSort(key: SortKey) {
    if (key === sortKey) setDir((d) => (d === 1 ? -1 : 1)); // same column: toggle asc/desc
    else {
      setSortKey(key);
      setDir(1);
    }
  }

  const rows = [...challenges].sort((a, b) => compare(a, b, sortKey, dir));

  return (
    <div className="mt-6 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-stone-500">
            {COLUMNS.map((c) => (
              <th key={c.key} className="py-2 pr-4 font-medium" title={c.title}>
                <button
                  onClick={() => onSort(c.key)}
                  className={`hover:text-stone-200 ${c.key === sortKey ? "text-stone-200" : ""}`}
                >
                  {c.label}
                  {c.key === sortKey ? (
                    <span aria-hidden className="ml-1 text-xs">{dir === 1 ? "▲" : "▼"}</span>
                  ) : null}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((ch) => (
            <tr key={ch.id} className="border-t border-stone-800">
              <td className="py-2 pr-4">
                <Link
                  href={`/challenges/${encodeURIComponent(ch.id)}`}
                  className="font-medium text-stone-100 hover:text-emerald-400"
                >
                  {ch.id}
                </Link>
                {ch.title ? <span className="ml-2 text-stone-500">{ch.title}</span> : null}
                {ch.deprecated ? (
                  <span className="ml-2 rounded bg-stone-800 px-1.5 py-0.5 text-xs text-stone-400">
                    deprecated
                  </span>
                ) : null}
              </td>
              <td className="py-2 pr-4 text-stone-400">{ch.category ?? "—"}</td>
              <td className="py-2 pr-4 text-stone-500">{ch.verification ?? "—"}</td>
              <td className="py-2 pr-4 tabular-nums text-stone-400">
                {ch.seed_difficulty ?? "—"}
              </td>
              <td className="py-2 pr-4">
                <PassRate r={ch.pass_rate} />
              </td>
              <td className="py-2 pr-4 tabular-nums text-stone-300">
                {ch.avg_score == null ? "—" : ch.avg_score.toFixed(3)}
              </td>
              <td className="py-2 pr-4 tabular-nums text-stone-500">{ch.n_runs}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

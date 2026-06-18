"""Apply externally-produced judge scores (e.g. from Claude in-session, or any judge that
isn't an OpenAI endpoint) into a comparable leaderboard.

  python -m bench.apply_judge <results-path> <scores.json> [--judge-name claude] [--out DIR]

scores.json format:
  {"judge": "claude",
   "scores": [{"model": "...", "challenge": "...",
               "correctness": 0-10, "readability": 0-10, "efficiency": 0-10,
               "rationale": "..."}]}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .challenges import load_challenges
from .report import write_report
from .runner import _load_results

ROOT = Path(__file__).resolve().parent.parent
CRITERIA = ["correctness", "readability", "efficiency"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("scores")
    ap.add_argument("--judge-name", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--challenges-dir", default=str(ROOT / "challenges"))
    args = ap.parse_args(argv)

    rows = _load_results(Path(args.results))
    blob = json.loads(Path(args.scores).read_text())
    judge_name = args.judge_name or blob.get("judge", "external")
    chmap = {c.id: c for c in load_challenges(Path(args.challenges_dir))}
    score_idx = {(s["model"], s["challenge"]): s for s in blob["scores"]}

    applied = 0
    for r in rows:
        s = score_idx.get((r["model"], r["challenge"]))
        if not s:
            continue
        scores = {c: float(s[c]) for c in CRITERIA if c in s}
        if not scores:
            continue
        norm = sum(scores.values()) / (10 * len(scores))
        r["judge_detail"] = {"scores": scores, "normalized": round(norm, 3),
                             "rationale": s.get("rationale", "")}
        r["judge_score"] = round(norm, 3)
        ch = chmap.get(r["challenge"])
        if ch and ch.scoring == "judge":
            r["final_score"] = round(norm, 3)
        elif ch and ch.scoring == "both":
            w = ch.judge_weight
            r["final_score"] = round((1 - w) * r.get("test_score", 0.0) + w * norm, 3)
        applied += 1

    if not applied:
        print("No scores matched any (model, challenge) row.", file=sys.stderr)
        return 1

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    src = Path(args.results)
    base = src.parent if (src.is_file() or src.name == "combined") else src
    outdir = Path(args.out) if args.out else base / f"judged-{judge_name}-{stamp}"
    meta = {"timestamp": stamp, "models": sorted({r["model"] for r in rows}),
            "n_challenges": len({r["challenge"] for r in rows}),
            "judge": judge_name, "sandbox": "external-judge", "judged": applied}
    write_report(rows, outdir, meta)
    print(f"Applied {applied} {judge_name} scores. Report: {outdir / 'leaderboard.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

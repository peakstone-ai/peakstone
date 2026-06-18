"""Export stored solutions from a run so an external judge (e.g. Claude in-session) can read
and grade them — no model endpoint required.

  python -m bench.export_solutions <results-path> [--out solutions.json] [--models a,b]

Output JSON: {"specs": {challenge_id: spec}, "items": [{model, challenge, language,
difficulty, scoring, passed, total, test_score, solution}]}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .challenges import load_challenges
from .extract import extract_files
from .runner import _load_results

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--out", default=None)
    ap.add_argument("--models", default=None)
    ap.add_argument("--ids", default=None)
    ap.add_argument("--challenges-dir", default=str(ROOT / "challenges"))
    args = ap.parse_args(argv)

    rows = _load_results(Path(args.results))
    chmap = {c.id: c for c in load_challenges(Path(args.challenges_dir))}
    only = [m.strip() for m in args.models.split(",")] if args.models else None
    only_ids = [i.strip() for i in args.ids.split(",")] if args.ids else None

    specs, items = {}, []
    for r in rows:
        if only and r["model"] not in only:
            continue
        if only_ids and r["challenge"] not in only_ids:
            continue
        ch = chmap.get(r["challenge"])
        resp = r.get("response") or ""
        if ch is None or not resp or resp.startswith("(reference") or r.get("note") == "error":
            continue
        files = extract_files(resp, ch.solution_file, ch.language)
        if not files:
            continue
        specs.setdefault(ch.id, ch.spec)
        items.append({
            "model": r["model"], "challenge": r["challenge"], "language": r["language"],
            "difficulty": r["difficulty"], "scoring": r["scoring"],
            "passed": r.get("passed", 0), "total": r.get("total", 0),
            "test_score": r.get("test_score", 0.0),
            "solution": "\n\n".join(f"### {p}\n{c}" for p, c in files.items()),
        })

    out = {"specs": specs, "items": items}
    text = json.dumps(out, indent=1)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {len(items)} solutions, {len(specs)} specs -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

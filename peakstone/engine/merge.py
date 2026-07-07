"""Merge several per-model results.json files into one combined leaderboard.

  python -m engine.merge results/bench-XXXX/*/results.json --out results/bench-XXXX/combined
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .report import write_report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="results.json files to merge")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    # Skip any already-merged combined/ file — re-merging a glob that catches the prior
    # combined output would double-count every row.
    inputs = [p for p in args.inputs if Path(p).parent.name != "combined"]
    dropped = [p for p in args.inputs if p not in inputs]
    if dropped:
        print(f"merge: skipping {len(dropped)} combined/ input(s) to avoid double-counting")

    all_results = []
    metas = []
    for p in inputs:
        data = json.loads(Path(p).read_text())
        all_results.extend(data["results"])
        metas.append(data.get("meta", {}))

    meta = {
        "models": sorted({m for mt in metas for m in mt.get("models", [])}),
        "n_challenges": max((mt.get("n_challenges", 0) for mt in metas), default=0),
        "judge": next((mt.get("judge") for mt in metas if mt.get("judge")), None),
        "sandbox": "subprocess",
        # carry host/run settings through the merge so the combined report keeps them
        "gpu": next((mt.get("gpu") for mt in metas if mt.get("gpu")), None),
        "retries": max((mt.get("retries", 0) or 0) for mt in metas) if metas else 0,
        "agents_md": any(mt.get("agents_md") for mt in metas),
        "coder_model": next((mt.get("coder_model") for mt in metas if mt.get("coder_model")), None),
        "merged_from": args.inputs,
    }
    # RUN IDENTITY carries through the merge (review R31: suite_id/max_tokens were dropped, so a
    # bundle produced from merged results re-stamped as 'adhoc' with the wrong recorded budget).
    # Set only when found: a present-but-None key would defeat produce_bundle's defaults.
    for k in ("suite_id", "suite_version", "max_tokens", "max_tokens_reasoning",
              "selected_ids", "judge_params"):
        v = next((mt.get(k) for mt in metas if mt.get(k)), None)
        if v is not None:
            meta[k] = v
    out = write_report(all_results, Path(args.out), meta)
    print(f"Combined report: {out / 'leaderboard.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

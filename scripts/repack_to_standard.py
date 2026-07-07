#!/usr/bin/env python3
"""Re-package a completed run's results to the CURRENT level selection — no re-run needed.

When the official suite is trimmed (smaller per-axis limits) and the new selection is a SUBSET of
what a prior full run already covered, re-running is wasteful: this filters that run's stored
results down to the current level's challenge ids and emits a fresh, correctly content-hashed +
signed bundle (re-derived from the unchanged challenge files + the run's stored meta, on this
machine — so it's faithful). Challenges the model legitimately couldn't run (e.g. a long-context
rung above its served ctx) just stay absent; the bundle reflects exactly what it ran.

  python scripts/repack_to_standard.py <results.json> [--level standard] [--submit URL] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

# script-style invocation puts scripts/ (not the repo root) on sys.path — make `peakstone` importable
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from peakstone.engine import bundle as B
from peakstone.engine import challenges as C
from peakstone.engine.levels import load_levels, resolve


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_json")
    ap.add_argument("--level", default="standard")
    ap.add_argument("--also", action="append", default=[],
                    help="extra results file(s) to APPEND unfiltered (e.g. an agentic env-results.json), "
                         "so the merged bundle shows coding + agentic in one leaderboard row")
    ap.add_argument("--overlay", action="append", default=[],
                    help="results file(s) whose rows REPLACE same-challenge rows in the base (e.g. a "
                         "self-repair retry of only the failures — recovered scores overwrite the originals)")
    ap.add_argument("--submit", help="API base url to POST the re-packaged bundle to")
    ap.add_argument("--out", help="output bundle path (default: <results dir>/bundle.repack.json)")
    args = ap.parse_args()

    chs = C.load_challenges(pathlib.Path("challenges"))
    ver, levels = load_levels()
    want = set(resolve(levels[args.level], chs))

    data = json.load(open(args.results_json))
    meta, rows = data["meta"], data["results"]
    kept = [r for r in rows if r.get("challenge") in want]
    covered = {r["challenge"] for r in kept}
    missing = want - covered
    model = (meta.get("models") or ["?"])[0]
    print(f"{model}: {len(rows)} stored results → kept {len(kept)} for level {args.level}@{ver}  "
          f"(covers {len(covered)}/{len(want)})")
    if missing:
        print(f"  not run by this model ({len(missing)}): {sorted(missing)}")

    # RETIRED (review R8): --overlay replaced first-attempt rows with retry rows and re-signed —
    # a composite indistinguishable from an honest single run. The headline is FIRST-TRY by
    # definition; recovered-by-retry is its own axis (recovery_rate), never an overwrite. Retries
    # belong in the run itself (--retries records attempts_log honestly), and judge scores come
    # from the judge-LAST pass (`runner --judge-only <run> --bundle`), not stitching.
    if args.overlay:
        sys.exit("--overlay is retired: it forged composites indistinguishable from honest runs "
                 "(review R8). Re-run with --retries, or use the judge-last pass for grading.")

    # append extra runs (e.g. agentic) unfiltered — they're a different axis, not part of the level set
    have = {r.get("challenge") for r in kept}
    for extra in args.also:
        ed = json.load(open(extra))
        erows = ed["results"] if isinstance(ed, dict) else ed   # env-results.json is a bare list
        fresh = [r for r in erows if r.get("challenge") not in have]
        kept += fresh
        have |= {r.get("challenge") for r in fresh}
        print(f"  + {len(fresh)} rows from {extra}")

    meta = {**meta, "suite_id": f"level-{args.level}", "suite_version": ver, "n_challenges": len(kept)}
    bundle = B.produce_bundle(meta, kept)
    out = pathlib.Path(args.out) if args.out else pathlib.Path(args.results_json).parent / "bundle.repack.json"
    B.write_bundle(bundle, out)
    print(f"  wrote {out}  (suite {bundle['suite']['id']}@{bundle['suite']['version']}, "
          f"content_hash {bundle['suite']['content_hash'][:12]}…, {len(bundle['results'])} results, "
          f"signed {bundle['submitter']['pubkey'][:12]}…)")

    if args.submit:
        from peakstone.dashboard.client import submit_bundle
        st, detail = submit_bundle(args.submit, bundle)
        print(f"  submit → HTTP {st}  {detail[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

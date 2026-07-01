# ⚠ COPYRIGHT NOTICE: SWE-bench tasks embed content from upstream GitHub repositories under varied licenses.
#   The generated corpus is gitignored and must NOT be committed or published to peakstone.ai.
#   Use only as PRIVATE challenges (you accept the upstream terms). Not part of the public suite.
"""Import SWE-bench-Live as peakstone repo-patch challenges (contamination-resistant agentic coding).

SWE-bench-Live is dated (each instance has created_at) and keeps adding recent GitHub issues, so it's
the one source that makes modern models held-out-scorable on *coding*. Each instance becomes a
`scoring="repo-patch"` challenge graded by engine/swebench.py (clone repo @ base_commit, apply patch,
run the repo's tests, check FAIL_TO_PASS pass + PASS_TO_PASS stay passing).

Source: SWE-bench-Live/SWE-bench-Live via the HF datasets-server rows API (no parquet dep), or a local
JSONL via --source. Default split 'lite' (300). --start-date filters by created_at for recency. Corpus
gitignored (regenerable; problems originate from GitHub repos).

Usage:
  python -m peakstone.engine.importers.swebench --split lite --start-date 2025-04-07
  python -m peakstone.engine.importers.swebench --source swebench_lite.jsonl --limit 50
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from .. import paths
from .humaneval import _slug

HF_DATASET = "SWE-bench-Live/SWE-bench-Live"
ROWS_API = "https://datasets-server.huggingface.co/rows"

# fields the harness needs; we copy these verbatim into instance.json
_KEEP = ("instance_id", "repo", "base_commit", "patch", "test_patch", "problem_statement",
         "test_cmds", "log_parser", "FAIL_TO_PASS", "PASS_TO_PASS", "created_at", "image")


def _fetch(split: str) -> list[dict]:
    rows: list[dict] = []
    off = 0
    while True:
        u = f"{ROWS_API}?dataset={HF_DATASET}&config=default&split={split}&offset={off}&length=100"
        with urllib.request.urlopen(u, timeout=60) as r:  # noqa: S310 (trusted host)
            batch = [x["row"] for x in json.load(r)["rows"]]
        rows += batch
        if len(batch) < 100:
            return rows
        off += 100


def image_name(instance_id: str, namespace: str = "starryzhang") -> str:
    """SWE-bench-Live prebuilt image: <namespace>/sweb.eval.x86_64.<id with __ -> _1776_>
    (Docker repo names disallow '__', so SWE-bench encodes it as '_1776_')."""
    return f"{namespace}/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}"


def _aslist(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return json.loads(v)
        except ValueError:
            return [v]
    return []


def _difficulty(inst: dict) -> int:
    d = inst.get("difficulty") or {}
    lines = d.get("lines", 0) if isinstance(d, dict) else 0
    return 3 if lines <= 15 else 4 if lines <= 60 else 5


def _meta(cid, title, difficulty, published_at, timeout) -> str:
    safe = str(title).replace("\\", "\\\\").replace('"', '\\"')[:80]
    return (
        f'id            = "{cid}"\n'
        f'title         = "{safe}"\n'
        f'language      = "python"\n'
        f"difficulty    = {difficulty}\n"
        f'category      = "swe"\n'
        f'type          = "repo-patch"\n'
        f'scoring       = "repo-patch"\n'
        f'solution_file = ""\n'
        f"timeout       = {timeout}\n"
        f'published_at  = "{published_at}"\n'
        f'published_at_source = "upstream"\n'
    )


def import_suite(records, out_root, suite, start_date, end_date, timeout, limit, namespace="starryzhang"):
    suite_dir = out_root / suite
    if suite_dir.exists():
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for r in records:
        date = (r.get("created_at") or "")[:10]
        if start_date and (not date or date < start_date):
            continue
        if end_date and (not date or date > end_date):
            continue
        if not (r.get("FAIL_TO_PASS") and r.get("base_commit") and r.get("repo")):
            skipped += 1
            continue
        if limit and written >= limit:
            break

        iid = r["instance_id"]
        cid = "swe-" + _slug(iid)
        inst = {k: r[k] for k in _KEEP if k in r and r[k] not in (None, "")}
        inst["FAIL_TO_PASS"] = _aslist(r.get("FAIL_TO_PASS"))
        inst["PASS_TO_PASS"] = _aslist(r.get("PASS_TO_PASS"))
        inst["test_cmds"] = _aslist(r.get("test_cmds")) or ["python -m pytest"]
        inst["instance_id"] = iid
        # prebuilt per-instance image (used only under runner --prebuilt). SWE-bench-Live convention:
        # <namespace>/sweb.eval.x86_64.<instance_id with __ -> _1776_>. image_key overrides if present.
        inst["image"] = r.get("image_key") or image_name(iid, namespace)

        cdir = suite_dir / cid
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "meta.toml").write_text(_meta(cid, iid, _difficulty(r), date, timeout))
        (cdir / "spec.md").write_text(f"# {iid}\n\n*{r.get('repo')} · {date}*\n\n"
                                      + (r.get("problem_statement") or "").rstrip() + "\n")
        (cdir / "instance.json").write_text(json.dumps(inst, indent=2))
        written += 1

    (suite_dir / "SOURCE.md").write_text(
        f"# SWE-bench-Live\n\n{written} repo-patch challenges auto-generated by "
        f"`peakstone.engine.importers.swebench`.\n\n"
        f"- **Source:** {HF_DATASET}\n"
        f"- **Grading:** clone repo @ base_commit, apply patch, run the repo's tests, check "
        f"FAIL_TO_PASS ∧ PASS_TO_PASS (engine/swebench.py). Agentic axis (verification=goal-state-env).\n"
        f"- **Contamination:** dated by created_at; SWE-bench-Live keeps adding recent issues, so newer "
        f"instances are held-out for earlier models.\n"
        f"- **Setup:** generic container (clone+pip install) by default; prebuilt per-instance image via "
        f"the instance `image` field. {skipped} skipped (no tests / missing fields).\n"
        f"- **License:** problems originate from GitHub repos; see each repo's license.\n")
    return written, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=None, help="local JSONL of instances (else fetch from HF)")
    ap.add_argument("--split", default="lite", help="SWE-bench-Live split: lite|test|verified|full")
    ap.add_argument("--out", default=None)
    ap.add_argument("--suite", default="swebench")
    ap.add_argument("--start-date", default=None, help="keep instances with created_at on/after YYYY-MM-DD")
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--timeout", type=int, default=1800, help="per-challenge test timeout (s)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--namespace", default="starryzhang", help="Docker Hub namespace for prebuilt images")
    args = ap.parse_args(argv)

    if args.source:
        records = [json.loads(l) for l in Path(args.source).read_text().splitlines() if l.strip()]
    else:
        records = _fetch(args.split)
    out_root = Path(args.out) if args.out else paths.challenges_dir()
    written, skipped = import_suite(records, out_root, args.suite, args.start_date, args.end_date,
                                    args.timeout, args.limit, args.namespace)
    print(f"imported {written} repo-patch challenges -> {out_root / args.suite}  ({skipped} skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

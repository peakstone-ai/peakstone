"""Import recent Codeforces problems (open-r1/codeforces) as peakstone challenges.

This is the answer to "newer than the models": LiveCodeBench is frozen at 2025-04, but
open-r1/codeforces carries each problem's real `contest_start` date well into 2025+, so filtering
to contests after a model's release gives genuine held-out coverage for modern models.

Codeforces problems are stdin/stdout, graded by the same subprocess shim as LiveCodeBench's stdin
mode. We import only cleanly-gradeable ones: `input_mode == "stdio"`, non-interactive, and NO
special-judge checker (exact-match output won't work for "any valid answer" problems). Test cases =
`official_tests` ∪ `examples`; note these are not always the full hidden set
(`official_tests_complete` is often False) — the omitted-count is logged, never hidden.

Source: the `verifiable` config via the HF datasets-server rows API (no parquet/`datasets` dep), or a
local JSONL via --source. No canonical solutions ship, so `--reference` skips this suite — validate
with a hand-written solution (as with LiveCodeBench).

Usage:
  # post-LCB-ceiling Codeforces problems (makes 2025+ models held-out-scorable)
  python -m peakstone.engine.importers.codeforces --start-date 2025-04-07
  # from the local cache, capped
  python -m peakstone.engine.importers.codeforces --source cf_verifiable.jsonl --start-date 2025-04-07 --limit 200
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from .. import paths
from .humaneval import _load_records, _slug

HF_DATASET = "open-r1/codeforces"
ROWS_API = "https://datasets-server.huggingface.co/rows"


def _fetch_rows(config: str = "verifiable", splits=("train", "test")) -> list[dict]:
    rows: list[dict] = []
    for split in splits:
        off = 0
        while True:
            u = (f"{ROWS_API}?dataset={HF_DATASET}&config={config}&split={split}"
                 f"&offset={off}&length=100")
            with urllib.request.urlopen(u, timeout=60) as r:  # noqa: S310 (trusted host)
                batch = [x["row"] for x in json.load(r)["rows"]]
            rows += batch
            if len(batch) < 100:
                break
            off += 100
    return rows


def _date(ts) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()


def gradeable(r: dict) -> bool:
    """Only problems our stdin/stdout shim can score: standard IO, no interactor, no special judge."""
    if (r.get("input_mode") or "stdio") != "stdio":
        return False
    if r.get("interaction_format"):
        return False
    if r.get("generated_checker"):
        return False
    return bool(r.get("official_tests") or r.get("examples"))


def _norm(s: str) -> str:
    return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def _cases(r: dict, max_cases: int) -> tuple[list, int]:
    seen, cases = set(), []
    for c in (r.get("official_tests") or []) + (r.get("examples") or []):
        inp, out = _norm(c.get("input", "")), _norm(c.get("output", ""))
        key = (inp, out)
        if inp and key not in seen:
            seen.add(key)
            cases.append({"input": inp, "output": out})
    kept = cases[:max_cases]
    return kept, len(cases) - len(kept)


def _cid(task_id: str) -> str:
    # "2063/A" -> "cf-2063-a"
    return "cf-" + task_id.replace("/", "-").lower()


def _difficulty(rating) -> int:
    if not isinstance(rating, (int, float)) or rating <= 0:
        return 3
    return 2 if rating <= 1000 else 3 if rating <= 1400 else 4 if rating <= 1900 else 5


def _toml_str(s: str) -> str:
    """Escape a value for a TOML basic string (Codeforces titles can contain quotes/backslashes)."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _meta(cid, title, difficulty, published_at, timeout) -> str:
    return (
        f'id            = "{cid}"\n'
        f'title         = "{_toml_str(title)}"\n'
        f'language      = "python"\n'
        f"difficulty    = {difficulty}\n"
        f'category      = "code-correctness"\n'
        f'type          = "algorithms"\n'
        f'scoring       = "tests"\n'
        f'solution_file = "solution.py"\n'
        f"timeout       = {timeout}\n"
        f'published_at  = "{published_at}"\n'
        f'published_at_source = "upstream"\n'
    )


def _spec(r: dict, n_cases: int, dropped: int) -> str:
    parts = [f"# {r.get('title', r['id'])}\n",
             f"*Codeforces · {r.get('contest_name', '')} · {_date(r.get('contest_start'))} · "
             f"rating {r.get('rating') or '?'}*\n",
             (r.get("description") or "").rstrip(), ""]
    if r.get("input_format"):
        parts += ["## Input", r["input_format"].rstrip(), ""]
    if r.get("output_format"):
        parts += ["## Output", r["output_format"].rstrip(), ""]
    for i, ex in enumerate(r.get("examples") or [], 1):
        parts += [f"### Example {i}", "Input:", "```", _norm(ex.get('input', '')).rstrip(), "```",
                  "Output:", "```", _norm(ex.get('output', '')).rstrip(), "```", ""]
    parts += ["Implement **`solution.py`** as a complete program that reads stdin and writes stdout.",
              f"\n<!-- open-r1/codeforces {r['id']}; graded on {n_cases} cases"
              f"{f' ({dropped} more omitted)' if dropped else ''} -->\n"]
    return "\n".join(parts)


def _stdin_test(ident: str, task_id: str) -> str:
    return f'''# Auto-generated from open-r1/codeforces {task_id}. Do not edit by hand.
# stdin/stdout problem: run solution.py as a subprocess, compare stdout per case.
import json, pathlib, subprocess, sys
import pytest

_D = pathlib.Path(__file__).parent
_CASES = json.loads((_D / "cases.json").read_text())["cases"]


def _norm(s: str) -> str:
    return "\\n".join(line.rstrip() for line in s.strip("\\n").split("\\n")).rstrip()


@pytest.mark.parametrize("i", range(len(_CASES)))
def test_{ident}(i):
    c = _CASES[i]
    p = subprocess.run([sys.executable, str(_D / "solution.py")],
                       input=c["input"], capture_output=True, text=True, timeout=15)
    assert p.returncode == 0, f"runtime error: {{p.stderr[-800:]}}"
    assert _norm(p.stdout) == _norm(c["output"]), (
        f"input={{c['input']!r}} expected={{c['output']!r}} got={{p.stdout!r}}")
'''


def import_suite(records, out_root, suite, start_date, end_date, max_cases, timeout, limit):
    suite_dir = out_root / suite
    if suite_dir.exists():
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = total_dropped = 0
    for r in records:
        date = _date(r.get("contest_start"))
        if start_date and (not date or date < start_date):
            continue
        if end_date and (not date or date > end_date):
            continue
        if not gradeable(r):
            skipped += 1
            continue
        cases, dropped = _cases(r, max_cases)
        if not cases:
            skipped += 1
            continue
        if limit and written >= limit:
            break

        cid = _cid(r["id"])
        ident = cid.replace("-", "_")
        slug = _slug(r.get("title", "")) or r["id"].replace("/", "-").lower()
        cdir = suite_dir / f"{cid}-{slug}"
        (cdir / "tests").mkdir(parents=True, exist_ok=True)

        (cdir / "meta.toml").write_text(
            _meta(cid, r.get("title", r["id"]), _difficulty(r.get("rating")), date, timeout))
        (cdir / "spec.md").write_text(_spec(r, len(cases), dropped))
        (cdir / "tests" / "cases.json").write_text(json.dumps({"mode": "stdin", "cases": cases}))
        (cdir / "tests" / f"test_{ident}.py").write_text(_stdin_test(ident, r["id"]))
        written += 1
        total_dropped += dropped

    (suite_dir / "SOURCE.md").write_text(
        f"# Codeforces ({HF_DATASET}, verifiable)\n\n"
        f"{written} challenges auto-generated by `peakstone.engine.importers.codeforces`.\n"
        f"Do not hand-edit; re-run the importer to refresh.\n\n"
        f"- **Source:** {HF_DATASET} (verifiable config)\n"
        f"- **License:** see upstream; problems originate from Codeforces — check their terms before "
        f"redistributing.\n"
        f"- **Window:** {start_date or 'start'} … {end_date or 'end'} (filter by contest date for "
        f"contamination resistance).\n"
        f"- **Grading:** stdin/stdout, ≤{max_cases} cases/problem (official_tests ∪ examples; "
        f"{total_dropped} omitted across the suite). Not always the full hidden set; interactive and "
        f"special-judge problems are skipped ({skipped} skipped total).\n"
        f"- **Note:** no canonical solutions ship — `--reference` skips this suite; validate with a "
        f"hand-written solution.\n"
    )
    return written, skipped, total_dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=None, help="local JSONL of rows (default: fetch verifiable config)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--suite", default="codeforces")
    ap.add_argument("--start-date", default=None, help="keep contests on/after YYYY-MM-DD")
    ap.add_argument("--end-date", default=None, help="keep contests on/before YYYY-MM-DD")
    ap.add_argument("--max-cases", type=int, default=30, help="max test cases embedded per problem")
    ap.add_argument("--timeout", type=int, default=20, help="per-challenge pytest timeout (s)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    records = _load_records(args.source) if args.source else _fetch_rows()
    out_root = Path(args.out) if args.out else paths.challenges_dir()
    written, skipped, dropped = import_suite(
        records=records, out_root=out_root, suite=args.suite,
        start_date=args.start_date, end_date=args.end_date,
        max_cases=args.max_cases, timeout=args.timeout, limit=args.limit,
    )
    print(f"imported {written} challenges -> {out_root / args.suite}  "
          f"({skipped} skipped, {dropped} cases omitted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

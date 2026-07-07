# ⚠ COPYRIGHT NOTICE: LiveCodeBench aggregates problems scraped from LeetCode/AtCoder/Codeforces — platform-copyrighted.
#   The generated corpus is gitignored and must NOT be committed or published to peakstone.ai.
#   Use only as PRIVATE challenges (you accept the upstream terms). Not part of the public suite.
"""Import LiveCodeBench (code generation) into peakstone challenges.

LiveCodeBench (https://huggingface.co/datasets/livecodebench/code_generation_lite,
problems scraped from LeetCode/AtCoder/Codeforces) is contamination-resistant: every
problem is dated, so filtering to contests after a model's training cutoff gives a clean
signal. That's the opposite of HumanEval/BigCodeBench (saturated/in-training-data), which
is why it's worth the extra machinery.

Two evaluation modes, both encoded here as generated pytest shims (no sandbox change):
  * stdin (AtCoder/Codeforces): the model writes a whole program; the test feeds each
    case's stdin to `solution.py` as a subprocess and compares stdout (whitespace-normalized).
  * functional (LeetCode): the model completes a `class Solution` method; the test execs
    solution.py with a competitive-programming import preamble, parses each case's
    newline-separated argument literals, calls the method, and compares the result.

Test cases are stored beside each challenge as cases.json (public + a capped slice of the
private cases; the cap is logged, never silent). The dataset ships NO canonical solutions,
so `--reference` runs skip these — validate the shim with a hand-written solution instead.

The source JSONLs are large (v1≈1.2GB … v6≈134MB) because every test case is embedded;
v6 is the default (smallest + most recent → most contamination-resistant).

Usage:
  python -m peakstone.engine.importers.livecodebench                 # v6, all problems
  python -m peakstone.engine.importers.livecodebench --start-date 2025-01-01 --max-cases 30
  python -m peakstone.engine.importers.livecodebench --version test4.jsonl --limit 50
"""
from __future__ import annotations

import argparse
import ast
import base64
import json
import shutil
import sys
import zlib
from pathlib import Path

from .. import paths
from ._common import meta_toml, stdin_test
from .humaneval import _slug

HF_DATASET = "livecodebench/code_generation_lite"

# A solution.py the model writes for a functional (LeetCode) task names types/containers
# (List, defaultdict, ...) without importing them — LiveCodeBench injects a preamble. We
# reproduce it so the candidate resolves the same names its author assumed.
_FUNCTIONAL_PREAMBLE = (
    "from typing import *\n"
    "import collections, math, heapq, bisect, itertools, functools, re, string, random\n"
    "from collections import *\n"
    "from math import *\n"
    "inf = float('inf')\n"
)


def _decode_private(s: str) -> list:
    if not s:
        return []
    try:
        return json.loads(zlib.decompress(base64.b64decode(s)))
    except (zlib.error, ValueError, base64.binascii.Error):
        return []


def _download(version: str) -> Path:
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(HF_DATASET, version, repo_type="dataset"))


def _cases(rec: dict, max_cases: int) -> tuple[list, int]:
    """All public cases, then private up to max_cases. Returns (cases, n_dropped)."""
    pub = json.loads(rec["public_test_cases"])
    priv = _decode_private(rec["private_test_cases"])
    keep = pub + priv[: max(0, max_cases - len(pub))]
    slim = [{"input": c["input"], "output": c["output"]} for c in keep]
    return slim, (len(pub) + len(priv)) - len(slim)


def _fn_name(starter_code: str) -> str | None:
    for line in starter_code.splitlines():
        s = line.strip()
        if s.startswith("def "):
            return s[4:].split("(", 1)[0].strip()
    return None


def _difficulty(d: str) -> int:
    return {"easy": 3, "medium": 4, "hard": 5}.get((d or "").lower(), 4)


def _meta(cid: str, title: str, difficulty: int, platform: str, mode: str, timeout: int,
          published_at: str) -> str:
    # published_at is the real contest date — LiveCodeBench's whole point: the
    # per-problem contamination boundary.
    return meta_toml(cid, title, "python", difficulty, "code-correctness", "algorithms",
                     "tests", "solution.py", timeout, published_at,
                     header=f"# {platform} / {mode}\n")


def _spec(rec: dict, mode: str, n_cases: int, dropped: int) -> str:
    head = f"# {rec['question_title']}\n\n"
    meta = (f"*Platform: {rec['platform']} · difficulty: {rec['difficulty']} · "
            f"contest date: {rec['contest_date'][:10]}*\n\n")
    body = rec["question_content"].rstrip() + "\n\n"
    if mode == "functional":
        how = ("Implement **`solution.py`** completing the class/method below. "
               "Keep the signature.\n\n```python\n" + rec["starter_code"].rstrip() + "\n```\n")
    else:
        how = ("Implement **`solution.py`** as a complete program that reads the problem's "
               "input from **stdin** and writes the answer to **stdout**.\n")
    note = (f"\n<!-- LiveCodeBench {rec['question_id']}; graded on {n_cases} cases"
            f"{f' ({dropped} additional private cases omitted)' if dropped else ''} -->\n")
    return head + meta + body + how + note


def _stdin_test(ident: str, question_id: str) -> str:
    return stdin_test(ident, "LiveCodeBench", question_id)


def _functional_test(ident: str, question_id: str, fn: str, preamble: str) -> str:
    return f'''# Auto-generated from LiveCodeBench {question_id}. Do not edit by hand.
# functional problem: exec solution with a competitive preamble, call Solution().{fn}(*args).
import json, pathlib
import pytest

_D = pathlib.Path(__file__).parent
{preamble}
exec((_D / "solution.py").read_text(), globals())
_CASES = json.loads((_D / "cases.json").read_text())["cases"]


def _parse(text: str):
    out = []
    for line in text.split("\\n"):
        if line == "":
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append(__import__("ast").literal_eval(line))
    return out


def _eq(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) <= 1e-6
        except (TypeError, ValueError):
            return a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    return a == b


@pytest.mark.parametrize("i", range(len(_CASES)))
def test_{ident}(i):
    c = _CASES[i]
    args = _parse(c["input"])
    expected = _parse(c["output"])
    expected = expected[0] if len(expected) == 1 else expected
    got = Solution().{fn}(*args)
    assert _eq(got, expected), f"args={{args!r}} expected={{expected!r}} got={{got!r}}"
'''


def import_suite(records, out_root, suite, id_prefix, version, start_date, end_date,
                 max_cases, timeout, limit):
    suite_dir = out_root / suite
    if suite_dir.exists():
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True, exist_ok=True)

    written = skipped_func = total_dropped = 0
    for rec in records:
        date = rec.get("contest_date", "")[:10]
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue
        if limit and written >= limit:
            break

        pub = json.loads(rec["public_test_cases"])
        mode = "functional" if pub and pub[0].get("testtype") == "functional" else "stdin"
        fn = _fn_name(rec["starter_code"]) if mode == "functional" else None
        if mode == "functional" and not fn:
            skipped_func += 1
            continue

        cases, dropped = _cases(rec, max_cases)
        total_dropped += dropped
        cid = f"{id_prefix}-{written:04d}"
        ident = cid.replace("-", "_")
        slug = _slug(rec["question_title"]) or rec["question_id"]
        cdir = suite_dir / f"{cid}-{slug}"
        (cdir / "tests").mkdir(parents=True, exist_ok=True)

        (cdir / "meta.toml").write_text(
            _meta(cid, rec["question_title"], _difficulty(rec["difficulty"]),
                  rec["platform"], mode, timeout, date))
        (cdir / "spec.md").write_text(_spec(rec, mode, len(cases), dropped))
        (cdir / "tests" / "cases.json").write_text(
            json.dumps({"mode": mode, "fn": fn, "cases": cases}))
        if mode == "stdin":
            (cdir / "tests" / f"test_{ident}.py").write_text(_stdin_test(ident, rec["question_id"]))
        else:
            (cdir / "tests" / f"test_{ident}.py").write_text(
                _functional_test(ident, rec["question_id"], fn, _FUNCTIONAL_PREAMBLE))
        written += 1

    (suite_dir / "SOURCE.md").write_text(
        f"# LiveCodeBench ({version})\n\n"
        f"{written} challenges auto-generated by `peakstone.engine.importers.livecodebench`.\n"
        f"Do not hand-edit; re-run the importer to refresh.\n\n"
        f"- **Source:** {HF_DATASET} ({version})\n"
        f"- **License:** see upstream; problems are scraped from LeetCode/AtCoder/Codeforces — "
        f"check each platform's terms before redistributing.\n"
        f"- **Window:** {start_date or 'start'} … {end_date or 'end'} (filter by contest_date for "
        f"contamination resistance).\n"
        f"- **Grading:** ≤{max_cases} cases/problem ({total_dropped} private cases omitted across the "
        f"suite); {skipped_func} functional tasks skipped (no parseable method).\n"
        f"- **Note:** no canonical solutions ship with LiveCodeBench, so `--reference` runs skip "
        f"this suite; validate with a hand-written solution.\n"
    )
    return written, skipped_func, total_dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default="test6.jsonl", help="dataset file: test.jsonl … test6.jsonl")
    ap.add_argument("--source", default=None, help="local JSONL override (skip download)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--suite", default="livecodebench")
    ap.add_argument("--id-prefix", default="lcb")
    ap.add_argument("--start-date", default=None, help="keep problems on/after YYYY-MM-DD")
    ap.add_argument("--end-date", default=None, help="keep problems on/before YYYY-MM-DD")
    ap.add_argument("--max-cases", type=int, default=25, help="max test cases embedded per problem")
    ap.add_argument("--timeout", type=int, default=90, help="per-challenge pytest timeout (s)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    path = Path(args.source) if args.source else _download(args.version)
    records = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    out_root = Path(args.out) if args.out else paths.challenges_dir()

    written, skipped_func, dropped = import_suite(
        records=records, out_root=out_root, suite=args.suite, id_prefix=args.id_prefix,
        version=args.version, start_date=args.start_date, end_date=args.end_date,
        max_cases=args.max_cases, timeout=args.timeout, limit=args.limit,
    )
    print(f"imported {written} challenges -> {out_root / args.suite}  "
          f"({skipped_func} functional skipped, {dropped} private cases omitted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Import a HumanEval-format benchmark into peakstone challenges.

The HumanEval JSONL schema — `task_id`, `prompt`, `canonical_solution`,
`test`, `entry_point` — is shared by OpenAI's original HumanEval *and* by the
EvalPlus release JSONLs (HumanEval+/MBPP+), so a single format-driven importer
covers all of them: just point `--source` at a different file/URL.

Each problem becomes challenges/<suite>/<id>-<slug>/ with:
  meta.toml              scoring = "tests", category = "code-correctness"
  spec.md                the function stub + docstring shown to the model
  reference/solution.py  prompt + canonical_solution (a known-passing solution)
  tests/test_*.py        a pytest shim that imports `solution` and runs check()

The test shim is the only non-trivial part: HumanEval expresses its tests as a
`def check(candidate): ...` string plus an `entry_point` name. We import that
entry point from the model's `solution.py` as `candidate`, paste the check
function verbatim, and add one pytest function that calls it — matching the
Python sandbox convention (tests live at the workdir root, `from solution
import ...`).

Usage:
  # default: OpenAI HumanEval (164 problems, MIT)
  python -m peakstone.engine.importers.humaneval

  # a handful, to sanity-check the pipeline
  python -m peakstone.engine.importers.humaneval --limit 5

  # EvalPlus HumanEval+ release JSONL (richer tests; Apache-2.0)
  python -m peakstone.engine.importers.humaneval \
      --source https://github.com/evalplus/humanevalplus_release/.../HumanEvalPlus.jsonl.gz \
      --suite humanevalplus --id-prefix hep \
      --source-name "EvalPlus HumanEval+" --license Apache-2.0

After importing, prove the generated tests pass against their own references:
  python -m peakstone.engine.runner --reference --models reference --type basic,algorithms
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

from .. import paths
from ._common import meta_toml

# OpenAI's canonical HumanEval data, MIT-licensed, pinned to the released file.
DEFAULT_SOURCE = "https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz"


def _load_records(source: str) -> list[dict]:
    """Read a (optionally gzipped) JSONL file from a local path or http(s) URL."""
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=60) as r:  # noqa: S310 (trusted benchmark host)
            raw = r.read()
    else:
        raw = Path(source).expanduser().read_bytes()
    if source.endswith(".gz") or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return [json.loads(line) for line in raw.decode().splitlines() if line.strip()]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "task"


def _num(task_id: str) -> str:
    """'HumanEval/42' -> '042'; falls back to a slug of the whole id."""
    tail = task_id.rsplit("/", 1)[-1]
    return f"{int(tail):03d}" if tail.isdigit() else _slug(tail)


def _difficulty(canonical_solution: str) -> int:
    """Coarse seed difficulty from solution size. The platform recalibrates from
    real submission data; this just keeps --difficulty filtering sane."""
    lines = [ln for ln in canonical_solution.splitlines() if ln.strip()]
    n = len(lines)
    if n <= 3:
        return 1
    if n <= 8:
        return 2
    if n <= 15:
        return 3
    return 4


# meta.toml requires an explicit `type` for grouping/filtering; "code-correctness"
# is a capability category, not a report type, so we map difficulty -> type here.
def _ctype(difficulty: int) -> str:
    return "basic" if difficulty <= 2 else "algorithms"


# HumanEval was published 2021-07-07 (the "Evaluating LLMs Trained on Code" release). Every
# problem shares that public date — the contamination boundary for any model trained after it.
PUBLISHED_AT = "2021-07-07"


def _meta(cid: str, title: str, difficulty: int, ctype: str, timeout: int) -> str:
    return meta_toml(cid, title, "python", difficulty, "code-correctness", ctype,
                     "tests", "solution.py", timeout, PUBLISHED_AT)


def _spec(prompt: str, source_name: str, task_id: str) -> str:
    return (
        f"# {task_id}\n\n"
        "Implement a file **`solution.py`** that completes the function below. "
        "Keep the given name and signature; your file must define it at module level.\n\n"
        "```python\n"
        f"{prompt.rstrip()}\n"
        "```\n\n"
        f"<!-- imported from {source_name} ({task_id}) -->\n"
    )


def _test_file(entry_point: str, test: str, ident: str, source_name: str, task_id: str) -> str:
    # Some HumanEval tests call a *helper* defined in the prompt (e.g. an oracle like
    # `sort_third`, `poly`, `encode_cyclic`) — the original harness execs the whole module so
    # those names are in scope. `import *` reproduces that; the alias names the entry point.
    return (
        f"# Auto-generated from {source_name} {task_id}. Do not edit by hand.\n"
        f"from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)\n"
        f"from solution import {entry_point} as candidate\n\n"
        f"{test.strip()}\n\n\n"
        f"def test_{ident}():\n"
        f"    check(candidate)\n"
    )


def _source_doc(suite: str, source: str, source_name: str, license_name: str, count: int) -> str:
    return (
        f"# {source_name}\n\n"
        f"These {count} challenges under `{suite}/` are auto-generated from an external "
        f"benchmark by `peakstone.engine.importers.humaneval`. Do not hand-edit; re-run the "
        f"importer to refresh.\n\n"
        f"- **Source:** {source}\n"
        f"- **License:** {license_name} — see the upstream project for full terms and "
        f"attribution requirements.\n"
        f"- **Format:** HumanEval JSONL (task_id, prompt, canonical_solution, test, entry_point).\n"
    )


def import_suite(
    source: str,
    out_root: Path,
    suite: str,
    id_prefix: str,
    source_name: str,
    license_name: str,
    timeout: int,
    limit: int | None,
) -> int:
    records = _load_records(source)
    if limit:
        records = records[:limit]
    suite_dir = out_root / suite
    suite_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for rec in records:
        task_id = rec["task_id"]
        entry_point = rec["entry_point"]
        num = _num(task_id)
        cid = f"{id_prefix}-{num}"
        slug = _slug(entry_point)
        cdir = suite_dir / f"{cid}-{slug}"
        (cdir / "tests").mkdir(parents=True, exist_ok=True)
        (cdir / "reference").mkdir(parents=True, exist_ok=True)

        diff = _difficulty(rec["canonical_solution"])
        ctype = _ctype(diff)
        ident = re.sub(r"\W", "_", cid)

        (cdir / "meta.toml").write_text(_meta(cid, task_id, diff, ctype, timeout))
        (cdir / "spec.md").write_text(_spec(rec["prompt"], source_name, task_id))
        (cdir / "reference" / "solution.py").write_text(
            rec["prompt"] + rec["canonical_solution"]
        )
        (cdir / "tests" / f"test_{ident}.py").write_text(
            _test_file(entry_point, rec["test"], ident, source_name, task_id)
        )
        written += 1

    (suite_dir / "SOURCE.md").write_text(
        _source_doc(suite, source, source_name, license_name, written)
    )
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help="HumanEval-format JSONL(.gz): local path or http(s) URL")
    ap.add_argument("--out", default=None,
                    help="challenges root to write under (default: the repo's challenges/)")
    ap.add_argument("--suite", default="humaneval", help="sub-directory + suite name")
    ap.add_argument("--id-prefix", default=None,
                    help="challenge id prefix (default: 'he' for humaneval, else first letters of suite)")
    ap.add_argument("--source-name", default="OpenAI HumanEval",
                    help="human-readable provenance recorded in spec/tests/SOURCE.md")
    ap.add_argument("--license", dest="license_name", default="MIT",
                    help="upstream license name recorded in SOURCE.md")
    ap.add_argument("--timeout", type=int, default=30, help="per-challenge test timeout (s)")
    ap.add_argument("--limit", type=int, default=None, help="import only the first N problems")
    args = ap.parse_args(argv)

    out_root = Path(args.out) if args.out else paths.challenges_dir()
    id_prefix = args.id_prefix or ("he" if args.suite == "humaneval" else _slug(args.suite)[:3])

    n = import_suite(
        source=args.source, out_root=out_root, suite=args.suite, id_prefix=id_prefix,
        source_name=args.source_name, license_name=args.license_name,
        timeout=args.timeout, limit=args.limit,
    )
    print(f"imported {n} challenges -> {out_root / args.suite}")
    print(f"verify: python -m peakstone.engine.runner --reference --models reference "
          f"--ids {id_prefix}-000")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Import BigCodeBench into peakstone challenges (library-fluency axis).

BigCodeBench (https://huggingface.co/datasets/bigcode/bigcodebench, Apache-2.0)
tests practical, library-heavy Python. Each task's row has:
  complete_prompt     imports + signature + full docstring (shown to the model)
  code_prompt         imports + signature stub
  canonical_solution  the function BODY (a known-passing solution)
  test                a `unittest.TestCase` class string referencing task_func
  entry_point         always "task_func"
  libs                the third-party/stdlib modules the task needs

It maps onto the Python sandbox like HumanEval: pytest runs unittest.TestCase
classes natively, and the test references task_func (+ helpers) by bare name, so
the `from solution import *` shim puts the whole solution module in scope.

The catch is DEPENDENCIES: BigCodeBench spans ~139 libraries (matplotlib,
sklearn, scipy, seaborn, ...). The subprocess sandbox runs in the harness's own
interpreter, so a task only passes where its libs are installed. Two modes:
  * default            emit the full, portable corpus (others with a complete
                       env — e.g. BigCodeBench's Docker image — can run it all)
  * --require-importable
                       emit only tasks whose libs all resolve in THIS
                       interpreter, for a clean local reference sanity check

Source: by default fetched as JSON via the HF datasets-server rows API (no
parquet/`datasets` dependency). `--source PATH` reads a local JSONL instead.

Usage:
  # local runnable slice, then sanity-check it
  python -m peakstone.engine.importers.bigcodebench --require-importable
  python -m peakstone.engine.runner --reference --models reference \
      --ids $(ls -d challenges/bigcodebench/bcb-*/ | sed -E 's#.*/(bcb-[0-9]+)-.*#\1#' | paste -sd,)

  # full portable corpus (run elsewhere with all deps installed)
  python -m peakstone.engine.importers.bigcodebench --suite bigcodebench
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from .. import paths
from .humaneval import _load_records, _slug

HF_DATASET = "bigcode/bigcodebench"
ROWS_API = "https://datasets-server.huggingface.co/rows"

# libs entries whose import name differs from the dependency name would go here;
# BigCodeBench already lists import-style names (PIL, bs4, cv2, sklearn, ...).
_ALIAS: dict[str, str] = {}


def _parse_libs(v) -> list[str]:
    if isinstance(v, list):
        return v
    try:
        return ast.literal_eval(v) if v else []
    except (ValueError, SyntaxError):
        return []


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(_ALIAS.get(name, name)) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _fetch_hf_rows(version: str) -> list[dict]:
    """Page the datasets-server rows API for the whole split (100 rows/call)."""
    rows: list[dict] = []
    off = 0
    while True:
        u = (f"{ROWS_API}?dataset={HF_DATASET}&config=default&split={version}"
             f"&offset={off}&length=100")
        with urllib.request.urlopen(u, timeout=60) as r:  # noqa: S310 (trusted host)
            batch = [x["row"] for x in json.load(r)["rows"]]
        rows += batch
        if len(batch) < 100:
            return rows
        off += 100


def _num(task_id: str) -> str:
    tail = task_id.rsplit("/", 1)[-1]
    return f"{int(tail):04d}" if tail.isdigit() else _slug(tail)


def _desc_slug(doc_struct: str) -> str:
    try:
        d = json.loads(doc_struct)
        words = " ".join(d.get("description", [])).split()[:6]
        return _slug(" ".join(words)) or "task"
    except (ValueError, TypeError):
        return "task"


def _difficulty(canonical_solution: str, n_libs: int) -> int:
    lines = len([ln for ln in canonical_solution.splitlines() if ln.strip()])
    base = 2 if lines <= 6 else 3 if lines <= 15 else 4 if lines <= 30 else 5
    return min(5, base + (1 if n_libs >= 4 else 0))


# BigCodeBench v0.1 was first released 2024-06; treat that as the public date of its problems
# (the contamination boundary). Override with --published-at for a more precise per-version date.
DEFAULT_PUBLISHED_AT = "2024-06-01"


def _meta(cid: str, title: str, difficulty: int, libs: list[str], timeout: int,
          published_at: str) -> str:
    return (
        f"# requires: {', '.join(libs) or 'stdlib only'}\n"
        f'id            = "{cid}"\n'
        f'title         = "{title}"\n'
        f'language      = "python"\n'
        f"difficulty    = {difficulty}\n"
        f'category      = "library-fluency"\n'
        f'type          = "lib-knowledge"\n'
        f'scoring       = "tests"\n'
        f'solution_file = "solution.py"\n'
        f"timeout       = {timeout}\n"
        f'published_at  = "{published_at}"\n'
        f'published_at_source = "upstream"\n'
    )


def _spec(complete_prompt: str, libs: list[str], task_id: str) -> str:
    reqs = ", ".join(f"`{l}`" for l in libs) or "the standard library only"
    return (
        f"# {task_id}\n\n"
        "Implement a file **`solution.py`** that completes the function below. "
        "Keep the given name and signature; define `task_func` at module level.\n\n"
        f"Allowed libraries: {reqs}.\n\n"
        "```python\n"
        f"{complete_prompt.rstrip()}\n"
        "```\n\n"
        f"<!-- imported from BigCodeBench ({task_id}) -->\n"
    )


def _test_file(test: str, ident: str, task_id: str) -> str:
    # BigCodeBench runs the candidate as `code + "\n" + test` in ONE module namespace, so the
    # solution sees names the test imports — a handful of canonical solutions use e.g. `np`
    # that only `import numpy as np` in the test provides. We reproduce that exactly: exec
    # solution.py into this module's globals, then run the test below in the same namespace.
    # (A plain `from solution import *` would isolate the solution and break those tasks.)
    return (
        f"# Auto-generated from BigCodeBench {task_id}. Do not edit by hand.\n"
        f"import pathlib as _pathlib\n"
        f'exec(_pathlib.Path(__file__).with_name("solution.py").read_text(), globals())\n\n'
        f"{test.strip()}\n"
    )


def import_suite(
    records: list[dict],
    out_root: Path,
    suite: str,
    id_prefix: str,
    version: str,
    timeout: int,
    require_importable: bool,
    limit: int | None,
    published_at: str = DEFAULT_PUBLISHED_AT,
) -> tuple[int, int]:
    suite_dir = out_root / suite
    if suite_dir.exists():
        shutil.rmtree(suite_dir)   # idempotent: filtering must not leave stale dirs
    suite_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for rec in records:
        libs = _parse_libs(rec.get("libs"))
        if require_importable and not all(_importable(l) for l in libs):
            skipped += 1
            continue
        if limit and written >= limit:
            break

        task_id = rec["task_id"]
        num = _num(task_id)
        cid = f"{id_prefix}-{num}"
        slug = _desc_slug(rec.get("doc_struct", ""))
        cdir = suite_dir / f"{cid}-{slug}"
        (cdir / "tests").mkdir(parents=True, exist_ok=True)
        (cdir / "reference").mkdir(parents=True, exist_ok=True)

        diff = _difficulty(rec["canonical_solution"], len(libs))
        ident = cid.replace("-", "_")

        (cdir / "meta.toml").write_text(_meta(cid, task_id, diff, libs, timeout, published_at))
        (cdir / "spec.md").write_text(_spec(rec["complete_prompt"], libs, task_id))
        (cdir / "reference" / "solution.py").write_text(
            rec["complete_prompt"] + rec["canonical_solution"]
        )
        (cdir / "tests" / f"test_{ident}.py").write_text(
            _test_file(rec["test"], ident, task_id)
        )
        written += 1

    (suite_dir / "SOURCE.md").write_text(
        f"# BigCodeBench ({version})\n\n"
        f"{written} challenges auto-generated by `peakstone.engine.importers.bigcodebench`.\n"
        f"Do not hand-edit; re-run the importer to refresh.\n\n"
        f"- **Source:** {HF_DATASET} (split {version})\n"
        f"- **License:** Apache-2.0 — see the upstream project for terms/attribution.\n"
        f"- **Filtering:** {'only tasks whose libs import in the current env' if require_importable else 'full corpus'}"
        f" ({skipped} skipped for missing deps).\n"
        f"- **Note:** running these requires each task's `# requires:` libs installed; the official "
        f"BigCodeBench Docker image pins a complete environment.\n"
    )
    return written, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=None, help="local JSONL of rows (default: fetch from HF)")
    ap.add_argument("--version", default="v0.1.4", help="BigCodeBench split, e.g. v0.1.4")
    ap.add_argument("--out", default=None, help="challenges root (default: repo challenges/)")
    ap.add_argument("--suite", default="bigcodebench")
    ap.add_argument("--id-prefix", default="bcb")
    ap.add_argument("--require-importable", action="store_true",
                    help="emit only tasks whose libs all import in the current interpreter")
    ap.add_argument("--timeout", type=int, default=60, help="per-challenge test timeout (s)")
    ap.add_argument("--limit", type=int, default=None, help="cap number of challenges written")
    ap.add_argument("--published-at", default=DEFAULT_PUBLISHED_AT,
                    help="public date of these problems (contamination boundary)")
    args = ap.parse_args(argv)

    records = _load_records(args.source) if args.source else _fetch_hf_rows(args.version)
    out_root = Path(args.out) if args.out else paths.challenges_dir()

    written, skipped = import_suite(
        records=records, out_root=out_root, suite=args.suite, id_prefix=args.id_prefix,
        version=args.version, timeout=args.timeout,
        require_importable=args.require_importable, limit=args.limit,
        published_at=args.published_at,
    )
    print(f"imported {written} challenges -> {out_root / args.suite}"
          f"  ({skipped} skipped for missing deps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Import GSM8K and Hendrycks MATH as peakstone answer-match challenges.

Two dated, MIT-licensed math word-problem sets that broaden the math axis below and beside AIME:

* **GSM8K** (``openai/gsm8k``, MIT) — grade-school arithmetic word problems. The gold answer is the
  integer after a ``#### <answer>`` line in the dataset's worked ``answer`` field.
* **Hendrycks MATH** (``hendrycks/competition_math``, MIT) — competition problems (levels 1-5,
  seven subjects). The gold answer is the last ``\\boxed{...}`` in the dataset's ``solution`` field
  (fractions, radicals and expressions, not just integers).

Both grade by deterministic answer-match, not code execution: the runner's ``scoring="answer-match"``
path (`peakstone.engine.matheval`) extracts the model's final answer and compares it to the gold in
meta ``expect``. So these join AIME on the math axis, a separate axis from ``code_score``.

Unlike AIME, neither set is contamination-free for current models — both predate the roster — but
they're dated by their release papers (``published_at``, ``published_at_source="upstream"``) so the
timeline logic still holds for anything trained before them, and they give dense, difficulty-graded
coverage that AIME's 30-a-year cannot.

Both are imported into one ``mathsets`` suite with distinct id prefixes (``gsm8k-``, ``math-``).

Usage:
  # default: GSM8K test + MATH test into challenges/mathsets/
  python -m peakstone.engine.importers.mathsets

  # a handful of each, to sanity-check the pipeline
  python -m peakstone.engine.importers.mathsets --limit 5

  # a single custom source (e.g. the MATH train split)
  python -m peakstone.engine.importers.mathsets --source hendrycks/competition_math \\
      --split train --kind boxed --published-at 2021-03-05 --id-prefix math

Grading is limited by `matheval` (integer-oriented extraction), so GSM8K scores cleanly today while
some non-integer MATH answers may under-score until the extractor is extended — the gold `expect` is
stored verbatim regardless, so re-scoring costs nothing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from .humaneval import _slug

ROWS_API = "https://datasets-server.huggingface.co/rows"


@dataclass
class Source:
    dataset: str
    split: str
    published_at: str          # release date of the set (its contamination boundary)
    id_prefix: str
    kind: str                  # "hashes" (GSM8K '#### N') or "boxed" (MATH '\boxed{...}')
    config: str = "default"
    problem_field: str = "question"
    answer_field: str = "answer"
    level_field: str = "level"      # MATH carries a 'Level k' difficulty; GSM8K has none
    label: str = "GSM8K"


# GSM8K: "Training Verifiers to Solve Math Word Problems" (Cobbe et al.), arXiv 2110.14168, 2021-10-27.
# MATH:  "Measuring Mathematical Problem Solving With the MATH Dataset" (Hendrycks et al.),
#        arXiv 2103.03874, 2021-03-05.
DEFAULT_SOURCES = [
    Source("openai/gsm8k", "test", "2021-10-27", "gsm8k", "hashes",
           config="main", problem_field="question", answer_field="answer", label="GSM8K"),
    Source("hendrycks/competition_math", "test", "2021-03-05", "math", "boxed",
           config="default", problem_field="problem", answer_field="solution", label="MATH"),
]


def _fetch(src: Source) -> list[dict]:
    rows: list[dict] = []
    off = 0
    while True:
        u = (f"{ROWS_API}?dataset={src.dataset}&config={src.config}&split={src.split}"
             f"&offset={off}&length=100")
        with urllib.request.urlopen(u, timeout=60) as r:  # noqa: S310 (trusted host)
            batch = [x["row"] for x in json.load(r)["rows"]]
        rows += batch
        if len(batch) < 100:
            return rows
        off += 100


def _gsm8k_answer(raw: str) -> str | None:
    """GSM8K stores the worked solution with the final answer after a '#### ' marker."""
    if "####" not in (raw or ""):
        return None
    ans = raw.split("####")[-1].strip()
    # gold answers are integers, sometimes thousands-separated / dollar-signed in the source.
    ans = ans.replace(",", "").replace("$", "").replace("%", "").strip()
    return ans or None


def _boxed_answer(raw: str) -> str | None:
    r"""Last ``\boxed{...}`` in a MATH solution, with balanced-brace matching so nested LaTeX like
    ``\boxed{\frac{1}{2}}`` is captured whole (the module-level regex in matheval only sees the
    innermost group — here we want the full contents)."""
    s = raw or ""
    idx = s.rfind("\\boxed")
    if idx == -1:
        return None
    i = idx + len("\\boxed")
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s) or s[i] != "{":
        return None
    depth = 0
    start = i
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                inner = s[start + 1:j].strip()
                return inner.strip("$").strip() or None
    return None


def _answer(src: Source, row: dict) -> str | None:
    raw = str(row.get(src.answer_field, ""))
    return _gsm8k_answer(raw) if src.kind == "hashes" else _boxed_answer(raw)


def _difficulty(src: Source, row: dict) -> int:
    """MATH ships a 'Level 1'..'Level 5' label; map it straight to difficulty. GSM8K is uniformly
    grade-school arithmetic — a flat, low-mid difficulty (the platform recalibrates from real runs)."""
    if src.kind == "hashes":
        return 2
    lvl = str(row.get(src.level_field, "")).strip()
    digits = "".join(c for c in lvl if c.isdigit())
    if digits:
        return max(1, min(5, int(digits)))
    return 3


def _toml_escape(s: str) -> str:
    """Escape a value for a basic (double-quoted) TOML string — MATH answers carry backslashes,
    quotes and the occasional newline."""
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\n", "\\n").replace("\t", "\\t").replace("\r", ""))


def _meta(cid, title, difficulty, answer, published_at, timeout) -> str:
    return (
        f'id            = "{cid}"\n'
        f'title         = "{title}"\n'
        f'language      = "text"\n'
        f"difficulty    = {difficulty}\n"
        f'category      = "math"\n'
        f'type          = "math"\n'
        f'scoring       = "answer-match"\n'
        f'expect        = "{_toml_escape(answer)}"\n'    # the gold final answer, verbatim
        f'solution_file = ""\n'
        f"timeout       = {timeout}\n"
        f'published_at  = "{published_at}"\n'
        f'published_at_source = "upstream"\n'
    )


def _spec(problem: str, src: Source, idx: int) -> str:
    return (f"# {src.label} Problem {idx}\n\n"
            f"{problem.rstrip()}\n\n"
            "Reason step by step, then give ONLY the final answer on the last line as "
            "\\boxed{ANSWER}.\n"
            f"\n<!-- imported from {src.dataset} ({src.split}) -->\n")


def import_suite(sources, out_root, suite, timeout, limit):
    suite_dir = out_root / suite
    if suite_dir.exists():
        shutil.rmtree(suite_dir)
    suite_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    per_source = []
    for src in sources:
        rows = _fetch(src)
        n = 0
        for i, r in enumerate(rows):
            if limit and n >= limit:      # --limit is per source, so both sets are represented
                break
            problem = str(r.get(src.problem_field, "")).strip()
            answer = _answer(src, r)
            if not problem or not answer:
                continue
            cid = f"{src.id_prefix}-{n:04d}"
            slug = _slug(problem[:50]) or "problem"
            cdir = suite_dir / f"{cid}-{slug}"
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "meta.toml").write_text(
                _meta(cid, f"{src.label} #{n + 1}", _difficulty(src, r), answer,
                      src.published_at, timeout))
            (cdir / "spec.md").write_text(_spec(problem, src, n + 1))
            n += 1
        per_source.append((src, n))
        total += n

    (suite_dir / "SOURCE.md").write_text(_source_doc(per_source, total))
    return total


def _source_doc(per_source, total) -> str:
    lines = [
        "# mathsets (GSM8K + Hendrycks MATH)",
        "",
        f"{total} answer-match challenges auto-generated by "
        "`peakstone.engine.importers.mathsets`. Do not hand-edit; re-run the importer to refresh.",
        "",
        "- **Grading:** deterministic answer-match (`peakstone.engine.matheval`); a separate axis "
        "from code_score.",
        "- **Format:** native peakstone answer-match — `scoring=\"answer-match\"`, `language=\"text\"`, "
        "gold answer in meta `expect`.",
        "",
        "## Sources",
        "",
    ]
    for src, n in per_source:
        lines.append(f"- **{src.label}** (`{src.dataset}`, {src.config}/{src.split}) — {n} problems, "
                     f"published {src.published_at}.")
    lines += [
        "",
        "## Attribution & License",
        "",
        "Both sets are distributed under the **MIT License**; see each upstream repository for the "
        "full license text and terms.",
        "",
        "- **GSM8K** — `openai/gsm8k`, MIT. Cobbe et al., *Training Verifiers to Solve Math Word "
        "Problems*, arXiv:2110.14168 (2021).",
        "- **Hendrycks MATH** — `hendrycks/competition_math`, MIT. Hendrycks et al., *Measuring "
        "Mathematical Problem Solving With the MATH Dataset*, arXiv:2103.03874 (NeurIPS 2021).",
        "",
        "The final answers stored in `expect` are extracted from each set's own solution field "
        "(GSM8K's `#### <answer>` marker; MATH's `\\boxed{...}`); the problem statements are "
        "reproduced verbatim in `spec.md`.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=None, help="single HF dataset id (else the built-in GSM8K+MATH set)")
    ap.add_argument("--config", default="default")
    ap.add_argument("--split", default="test")
    ap.add_argument("--kind", choices=["hashes", "boxed"], default="boxed",
                    help="final-answer format: 'hashes' (GSM8K '#### N') or 'boxed' (MATH \\boxed{})")
    ap.add_argument("--problem-field", default=None, help="row field with the problem statement")
    ap.add_argument("--answer-field", default=None, help="row field with the worked solution/answer")
    ap.add_argument("--published-at", default=None, help="release date YYYY-MM-DD (required with --source)")
    ap.add_argument("--id-prefix", default="math")
    ap.add_argument("--label", default=None, help="human-readable set name for titles/spec/SOURCE.md")
    ap.add_argument("--out", default=None)
    ap.add_argument("--suite", default="mathsets")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--limit", type=int, default=None, help="import only the first N problems per source")
    args = ap.parse_args(argv)

    if args.source:
        if not args.published_at:
            ap.error("--published-at is required with --source")
        pf = args.problem_field or ("question" if args.kind == "hashes" else "problem")
        af = args.answer_field or ("answer" if args.kind == "hashes" else "solution")
        sources = [Source(args.source, args.split, args.published_at, args.id_prefix, args.kind,
                          args.config, pf, af, label=args.label or args.id_prefix.upper())]
    else:
        sources = DEFAULT_SOURCES

    out_root = Path(args.out) if args.out else paths.challenges_dir()
    n = import_suite(sources, out_root, args.suite, args.timeout, args.limit)
    print(f"imported {n} math challenges -> {out_root / args.suite}")
    print(f"verify: python -m peakstone.engine.runner --models <live-model> --suite {args.suite} --limit 3")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared helpers for the benchmark importers (review R30 deduplication).

Three pieces of machinery were copy-pasted across the importers and now live here:
the HF datasets-server pagination loop (`hf_rows`), the stdin/stdout pytest shim
(`stdin_test`) and the meta.toml writer (`meta_toml`) with its TOML string escapers.

Behavior-preserving by construction: challenge files (meta.toml, spec.md, tests) are
content-hashed, so every helper must reproduce its originating importer's output
byte-for-byte for the same inputs. Where importers differed, the difference is a
parameter here (e.g. `header`, `expect`, the shim's source label) — never a change
in the emitted bytes.
"""
from __future__ import annotations

import json
import urllib.request

ROWS_API = "https://datasets-server.huggingface.co/rows"


def hf_rows(dataset: str, config: str, split: str) -> list[dict]:
    """Page the HF datasets-server rows API for one whole split (100 rows/call)."""
    rows: list[dict] = []
    off = 0
    while True:
        u = (f"{ROWS_API}?dataset={dataset}&config={config}&split={split}"
             f"&offset={off}&length=100")
        with urllib.request.urlopen(u, timeout=60) as r:  # noqa: S310 (trusted host)
            batch = [x["row"] for x in json.load(r)["rows"]]
        rows += batch
        if len(batch) < 100:
            return rows
        off += 100


def toml_escape(s) -> str:
    """Escape a value for a TOML basic (double-quoted) string: backslashes + quotes
    (benchmark titles can contain both)."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def toml_escape_multiline(s: str) -> str:
    """`toml_escape` plus newline/tab escaping and CR removal — for values that may
    span lines (e.g. MATH gold answers)."""
    return (toml_escape(s)
            .replace("\n", "\\n").replace("\t", "\\t").replace("\r", ""))


def meta_toml(cid: str, title: str, language: str, difficulty: int, category: str,
              ctype: str, scoring: str, solution_file: str, timeout: int,
              published_at: str, *, expect: str | None = None, header: str = "") -> str:
    """The common meta.toml body shared by all importers.

    `header` is an optional leading comment line ("# ...\\n"); `expect` inserts the
    gold-answer line used by answer-match suites. `title` and `expect` are emitted
    verbatim — callers escape them (or not) exactly as they did before this refactor.
    """
    expect_line = f'expect        = "{expect}"\n' if expect is not None else ""
    return (
        header
        + f'id            = "{cid}"\n'
        f'title         = "{title}"\n'
        f'language      = "{language}"\n'
        f"difficulty    = {difficulty}\n"
        f'category      = "{category}"\n'
        f'type          = "{ctype}"\n'
        f'scoring       = "{scoring}"\n'
        + expect_line
        + f'solution_file = "{solution_file}"\n'
        f"timeout       = {timeout}\n"
        f'published_at  = "{published_at}"\n'
        f'published_at_source = "upstream"\n'
    )


def stdin_test(ident: str, source: str, ref: str) -> str:
    """Pytest shim for stdin/stdout problems: run solution.py as a subprocess per case.

    `source`/`ref` only label the provenance comment (e.g. "LiveCodeBench" + question
    id, "open-r1/codeforces" + task id); the shim body is identical for both.
    """
    return f'''# Auto-generated from {source} {ref}. Do not edit by hand.
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

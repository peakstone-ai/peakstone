"""No-LLM efficiency metrics — deterministic, judge-free sub-scores on a solution (PLAN.md §9 P2).

These are *additional sortable axes*, not part of the correctness score: a model can be
correct-but-bloated vs correct-and-lean. v1 is the cross-language set that applies to every
challenge — code size (loc, bytes), memory (peak RSS of the test run), and speed (test wall time).
Binary/artifact size + compile time come later (they need executable challenges or a perf harness;
the current corpus is library+tests, with no `main` to build).
"""
from __future__ import annotations

import re


def collect_static(files: dict[str, str]) -> dict:
    """Source-size metrics, computed from the solution text alone (no execution)."""
    loc = sum(1 for content in files.values() for line in content.splitlines() if line.strip())
    sol_bytes = sum(len(content.encode("utf-8")) for content in files.values())
    return {"loc": loc, "solution_bytes": sol_bytes}


_RSS_RE = re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)")


def parse_peak_rss_kb(time_v_output: str) -> int | None:
    """Pull peak RSS (KiB) out of GNU `/usr/bin/time -v` output."""
    m = _RSS_RE.search(time_v_output)
    return int(m.group(1)) if m else None

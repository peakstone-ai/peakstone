"""Optional global AGENTS.md applied to every code-gen challenge (runner --agents-md).

Generalises the per-challenge instruction-adherence machinery to the WHOLE suite, the way
--retries generalised agentic self-repair. When enabled, AGENTS_MD is appended to the system
prompt for each tests/both challenge (a sane output contract that mainly helps reasoning models
reach a complete answer), and RULES are scored deterministically on each response as a separate
**global adherence** axis. It does NOT change correctness / final scores.

Rule set (chosen 2026-06-18): keep reasoning concise + use the exact requested file name. The
strict "no prose outside code" rule is deliberately omitted — it would penalise <think>-style
reasoning models, the very models this is meant to give a fairer shot.
"""
from __future__ import annotations

import re

AGENTS_MD = """\
# Output conventions (apply to every task)

- Think briefly. Do not spend your whole output budget reasoning: reach the solution quickly and
  make sure the COMPLETE solution code is emitted before you stop.
- Write the solution to the EXACT file name the task requests, using the exact function / type
  signatures it specifies. Do not rename the file, functions, or types.
"""

# prose outside code longer than this (after stripping <think>) counts as "not concise"
_PROSE_LIMIT = 1500

_FENCE = re.compile(r"```[^\n`]*\n.*?```", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove <think>…</think> reasoning so a planner's monologue doesn't leak into the plan
    the coder sees. Also drops a dangling unclosed <think> (truncated reasoning with no plan)."""
    t = _THINK.sub("", text or "")
    i = t.lower().find("<think>")
    if i != -1:
        t = t[:i]
    return t.strip()


def _prose(response: str) -> str:
    """Response with fenced code blocks and <think>…</think> removed (brief thinking is fine)."""
    t = _FENCE.sub("", response or "")
    t = _THINK.sub("", t)
    return t.strip()


def concise_reasoning(response: str, files: dict, ch) -> bool:
    """Pass when the answer isn't buried in long out-of-band prose (<think> excluded)."""
    return len(_prose(response)) <= _PROSE_LIMIT


def exact_filename(response: str, files: dict, ch) -> bool:
    """Pass when the requested solution file is among the emitted files (model didn't rename it)."""
    sf = getattr(ch, "solution_file", None)
    if not sf:
        return True
    names = {f.rsplit("/", 1)[-1] for f in files}
    return sf in files or sf.rsplit("/", 1)[-1] in names


RULES = [
    ("concise_reasoning", concise_reasoning),
    ("exact_filename", exact_filename),
]


def evaluate(response: str, files: dict, ch):
    """Return (passed, total, detail) for the global rules against one response."""
    detail = [(name, bool(fn(response, files, ch))) for name, fn in RULES]
    return sum(1 for _, ok in detail if ok), len(detail), detail


def load_agents_md(value: str) -> str:
    """Resolve the --agents-md value: the sentinel uses the built-in default, else read a file."""
    if value in (None, "__default__"):
        return AGENTS_MD
    from pathlib import Path
    return Path(value).read_text()

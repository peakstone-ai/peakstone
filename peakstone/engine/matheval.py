"""Deterministic answer-matching for math problems (AIME-style integer answers).

The model reasons in free text and states a final answer; we extract it and compare to the gold
value. Pure + dependency-free so it's testable and reused by the runner's answer-match scoring.
"""
from __future__ import annotations

import re

_BOXED = re.compile(r"\\boxed\s*\{([^{}]*)\}")
_INT = re.compile(r"-?\d+")
_FINAL = re.compile(r"(?:final\s+answer|the\s+answer\s+is|answer)\s*[:=]?\s*\$?\\?\(?\s*(-?\d+)", re.I)


def _last_int(s: str) -> str | None:
    ms = _INT.findall(s or "")
    return ms[-1] if ms else None


def extract_answer(text: str) -> str | None:
    """Best-effort final integer answer from a reasoning trace. Priority: last \\boxed{...},
    then an explicit 'answer is N' phrasing, then the last integer in the text."""
    if not text:
        return None
    boxed = _BOXED.findall(text)
    if boxed:
        n = _last_int(boxed[-1])
        if n is not None:
            return n
    m = _FINAL.findall(text)
    if m:
        return m[-1]
    return _last_int(text)


def answers_match(got, gold) -> bool:
    """Compare extracted vs gold. Integer-compare when both parse as ints (handles leading zeros,
    '007' == '7'); else exact string compare."""
    if got is None or gold is None:
        return False
    g, gd = str(got).strip(), str(gold).strip()
    try:
        return int(g) == int(gd)
    except (ValueError, TypeError):
        return g == gd

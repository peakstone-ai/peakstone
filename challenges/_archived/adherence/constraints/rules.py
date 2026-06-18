"""Deterministic checks for the hard-constraints AGENTS.md (incl. output-format on `response`)."""
import re


def _only_process(s, r):
    funcs = re.findall(r'^\s*def\s+(\w+)\s*\(', s, re.M)
    classes = re.findall(r'^\s*class\s+\w+', s, re.M)
    return funcs == ['process'] and not classes


def _max_lines(s, r):
    return len([ln for ln in s.splitlines() if ln.strip()]) <= 25


def _no_prose(s, r):
    # strip fenced code blocks from the raw response; little text should remain
    stripped = re.sub(r'```.*?```', '', r or '', flags=re.DOTALL)
    return len(stripped.strip()) < 40


RULES = [
    {"name": "only_process", "desc": "exactly one function named process", "check": _only_process},
    {"name": "no_imports", "desc": "no imports",
     "check": lambda s, r: not re.search(r'^\s*(import|from)\s', s, re.M)},
    {"name": "max_25_lines", "desc": "<= 25 lines", "check": _max_lines},
    {"name": "output_only_code", "desc": "response is only the code block, no prose",
     "check": _no_prose},
]

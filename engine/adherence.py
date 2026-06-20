"""Instruction-adherence scoring.

The model is given a project `agent.md` (standing conventions) as its system prompt plus a
task, and we score how many of the challenge's deterministically-checkable RULES the produced
code obeys — independent of whether the code is functionally correct. This isolates
*instruction following* from *coding ability*.

Each adherence challenge dir contains:
  agent.md     the standing conventions (becomes the system prompt)
  spec.md      the task shown to the model
  rules.py     defines RULES = [{"name","desc","check"}], check(solution, response) -> bool
  reference/   a solution that obeys every rule (sanity-checks the rules)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ADHERENCE_SYSTEM = (
    "You are a coding agent working inside a project. The project's AGENTS.md below lists "
    "MANDATORY conventions — follow every one of them in the code you write. Output only the "
    "requested solution file as a single fenced code block.\n\n===== AGENTS.md =====\n{agent_md}\n"
    "===== end AGENTS.md =====\n"
)


def load_rules(challenge_dir: Path, filename: str = "rules.py"):
    p = challenge_dir / filename
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"rules_{challenge_dir.name}_{filename}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def evaluate(rules_mod, solution: str, response: str):
    """Return (passed, total, detail) where detail is a list of (rule_name, ok, desc)."""
    detail = []
    for rule in rules_mod.RULES:
        try:
            ok = bool(rule["check"](solution, response))
        except Exception:  # noqa: BLE001
            ok = False
        detail.append((rule["name"], ok, rule.get("desc", "")))
    passed = sum(1 for _, ok, _ in detail if ok)
    return passed, len(detail), detail

"""Discover and load challenges from the challenges/ tree.

Each challenge directory contains:
  spec.md            prompt shown to the model
  meta.toml          metadata (schema below)
  tests/             language-native test files
  reference/         reference solution (optional; used for --reference sanity runs)

meta.toml schema:
  id            = "py-01-fizzbuzz"
  title         = "FizzBuzz"
  language      = "python" | "javascript" | "typescript" | "go" | "rust"
  difficulty    = 1..5
  category      = "basics"
  scoring       = "tests" | "judge" | "both"
  solution_file = "solution.py"        # where the model's code is written
  timeout       = 30                    # seconds for the test run
  [judge]                               # only for scoring = judge|both
  weight   = 0.3                        # judge fraction of final score (rest = tests)
  criteria = ["correctness", "readability", "efficiency"]
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# coarse grouping used in reports; meta.toml may set `type` explicitly, else inferred here.
_CATEGORY_TYPE = {
    "basics": "basic", "data": "data", "algorithms": "algorithms", "parsing": "algorithms",
    "interpreters": "algorithms", "graphs": "lib-knowledge", "systems": "data-structures",
    "data-structures": "data-structures", "numpy": "math", "pandas": "lib-knowledge",
    "validation": "lib-knowledge", "uncommon-libs": "lib-knowledge", "libraries": "lib-knowledge",
    "generics": "typing", "concurrency": "concurrency", "async": "concurrency",
    "tool-calling": "tool-calling",
}


@dataclass
class Challenge:
    id: str
    title: str
    language: str
    difficulty: int
    category: str
    scoring: str
    solution_file: str
    timeout: int
    dir: Path
    spec: str
    ctype: str = "other"
    expect: str = ""          # for refusal challenges: "answer" | "refuse"
    judge_weight: float = 0.3
    judge_criteria: list[str] = field(default_factory=lambda: ["correctness", "readability", "efficiency"])

    def reference_files(self) -> dict[str, str]:
        """Return {relative_path: content} from reference/, mapped onto solution layout."""
        ref = self.dir / "reference"
        if not ref.is_dir():
            return {}
        out: dict[str, str] = {}
        for f in ref.rglob("*"):
            if f.is_file():
                out[str(f.relative_to(ref))] = f.read_text()
        return out


def load_challenges(root: Path) -> list[Challenge]:
    out: list[Challenge] = []
    for meta in sorted(root.rglob("meta.toml")):
        d = meta.parent
        # skip disabled/archived trees: any path component starting with "_" or "." (e.g.
        # challenges/_archived/) is excluded from the active suite.
        if any(part[:1] in ("_", ".") for part in d.relative_to(root).parts):
            continue
        m = tomllib.loads(meta.read_text())
        spec = (d / "spec.md").read_text() if (d / "spec.md").exists() else ""
        j = m.get("judge", {})
        cat = m.get("category", "")
        ctype = m.get("type") or _CATEGORY_TYPE.get(cat, "other")
        out.append(Challenge(
            id=m["id"], title=m["title"], language=m["language"],
            difficulty=int(m["difficulty"]), category=cat,
            scoring=m.get("scoring", "tests"), solution_file=m.get("solution_file", ""),
            timeout=int(m.get("timeout", 30)), dir=d, spec=spec, ctype=ctype,
            expect=m.get("expect", ""),
            judge_weight=float(j.get("weight", 0.3)),
            judge_criteria=list(j.get("criteria", ["correctness", "readability", "efficiency"])),
        ))
    return out


def filter_challenges(chs, langs=None, difficulties=None, ids=None, categories=None, types=None):
    def keep(c):
        if langs and c.language not in langs:
            return False
        if difficulties and c.difficulty not in difficulties:
            return False
        if ids and c.id not in ids:
            return False
        if categories and c.category not in categories:
            return False
        if types and c.ctype not in types:
            return False
        return True
    return [c for c in chs if keep(c)]

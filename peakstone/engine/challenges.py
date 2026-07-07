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
  published_at  = "2021-07-07"          # optional: date the content first became public
  published_at_source = "upstream"      # optional: upstream|platform-first-seen|git|author
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
    kind: str = "code"        # "code" | "env" — one base type, discriminated (review R28);
    #                           goal-state-env challenges are env.spec.EnvChallenge (kind="env")
    ctype: str = "other"
    expect: str = ""          # for refusal challenges: "answer" | "refuse"
    min_ctx: int = 0          # long-context: minimum served context window to attempt (0 = no requirement)
    published_at: str = ""    # date the challenge content first became public (YYYY-MM-DD)
    published_at_source: str = ""  # upstream | platform-first-seen | git | author | unknown
    judge_weight: float = 0.3
    judge_criteria: list[str] = field(default_factory=lambda: ["correctness", "readability", "efficiency"])

    @property
    def family(self) -> str:
        """The corpus group this challenge belongs to — the directory under challenges/
        (e.g. 'humaneval', 'bigcodebench', 'livecodebench', 'python'). The unit the TUI and
        --family filter browse/select by."""
        return self.dir.parent.name

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


def _active_dirs(root: Path):
    """Every active challenge dir under root (a meta.toml parent), skipping disabled/archived
    trees: any path component starting with "_" or "." (e.g. challenges/_archived/) is excluded
    from the active suite."""
    for meta in sorted(root.rglob("meta.toml")):
        d = meta.parent
        if any(part[:1] in ("_", ".") for part in d.relative_to(root).parts):
            continue
        yield d


def load_challenges(root: Path, kind: str = "code") -> list[Challenge]:
    """Load the corpus — ONE walk + skip rule for both challenge kinds (review R28). `kind`
    selects which: "code" (default — same corpus existing consumers always saw) or "env",
    the goal-state-env (multi-machine) challenges, discriminated on disk by an env.toml
    topology + verify.py and constructed by engine.env.spec as EnvChallenge (a Challenge
    subclass). env.load_env_challenges is the public alias for kind="env"."""
    out: list[Challenge] = []
    for d in _active_dirs(root):
        if (d / "env.toml").exists():
            if kind == "env" and (d / "verify.py").exists():
                from .env.spec import load_env_challenge   # lazy — env.spec subclasses Challenge
                out.append(load_env_challenge(d))
            continue
        if kind != "code":
            continue
        m = tomllib.loads((d / "meta.toml").read_text())
        spec = (d / "spec.md").read_text() if (d / "spec.md").exists() else ""
        j = m.get("judge", {})
        cat = m.get("category", "")
        ctype = m.get("type") or _CATEGORY_TYPE.get(cat, "other")
        out.append(Challenge(
            id=m["id"], title=m["title"], language=m["language"],
            difficulty=int(m["difficulty"]), category=cat,
            scoring=m.get("scoring", "tests"), solution_file=m.get("solution_file", ""),
            timeout=int(m.get("timeout", 30)), dir=d, spec=spec, ctype=ctype,
            expect=m.get("expect", ""), min_ctx=int(m.get("min_ctx", 0)),
            published_at=str(m.get("published_at", "")),
            published_at_source=m.get("published_at_source", ""),
            judge_weight=float(j.get("weight", 0.3)),
            judge_criteria=list(j.get("criteria", ["correctness", "readability", "efficiency"])),
        ))
    return out


def challenge_source(cid: str, root: Path | None = None) -> dict | None:
    """Public source (spec + test files) for a challenge id, read from the corpus. Returns None if
    the challenge isn't in the public source — absent, archived (``_*``), or under ``private/`` —
    so copyright-encumbered / private challenges are never exposed. Powers the web solution viewer."""
    from . import paths
    root = root or paths.challenges_dir()
    if not root.exists():
        return None
    # never expose non-public trees: private/, archived (_*), or the copyright-encumbered imports
    # (defense-in-depth — they're gitignored + .dockerignore'd, so normally absent from the image)
    nonpublic = {"private", "codeforces", "aime", "livecodebench", "swebench"}
    for meta in sorted(root.rglob("meta.toml")):
        d = meta.parent
        rel = d.relative_to(root)
        if rel.parts and (rel.parts[0] in nonpublic
                          or any(p[:1] in ("_", ".") for p in rel.parts)):
            continue
        try:
            m = tomllib.loads(meta.read_text())
        except Exception:  # noqa: BLE001
            continue
        if m.get("id") != cid:
            continue
        tests: dict[str, str] = {}
        tdir = d / "tests"
        if tdir.is_dir():
            for f in sorted(tdir.rglob("*")):
                if f.is_file():
                    try:
                        tests[str(f.relative_to(tdir))] = f.read_text()
                    except Exception:  # noqa: BLE001
                        pass
        spec = d / "spec.md"
        return {
            "id": cid, "title": m.get("title"), "language": m.get("language"),
            "category": m.get("category"), "difficulty": m.get("difficulty"),
            "scoring": m.get("scoring"),
            "spec": spec.read_text() if spec.is_file() else None,
            "tests": tests,
        }
    return None


def _date10(s) -> str:
    """First 10 chars of an ISO date string if well-formed, else "" (ISO dates sort chronologically)."""
    d = (s or "").strip()[:10]
    return d if (len(d) == 10 and d[4] == "-" and d[7] == "-") else ""


def filter_challenges(chs, langs=None, difficulties=None, ids=None, categories=None, types=None,
                      families=None, published_after=None, published_before=None, served_ctx=None):
    """Keep challenges matching ALL active filters. families filters on Challenge.family; the
    published_* bounds (YYYY-MM-DD) compare on published_at and EXCLUDE undated challenges when a
    date bound is active (an unknown date can't be proven in-range). served_ctx drops long-context
    challenges whose min_ctx exceeds the run's served window (the model literally can't fit them —
    attempting would just truncate and fail unfairly)."""
    after, before = _date10(published_after), _date10(published_before)

    def keep(c):
        if served_ctx is not None and c.min_ctx and c.min_ctx > served_ctx:
            return False
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
        if families and c.family not in families:
            return False
        if after or before:
            pub = _date10(c.published_at)
            if not pub:
                return False
            if after and pub < after:
                return False
            if before and pub > before:
                return False
        return True
    return [c for c in chs if keep(c)]

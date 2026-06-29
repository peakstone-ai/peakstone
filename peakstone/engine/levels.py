"""Test levels: named, versioned recipes mapping a time/compute budget to a deterministic challenge
selection + run settings. Defined in levels.toml.

A level resolves against the current corpus to an ORDERED, unique, model-independent id list (so the
same axis is comparable across models/quants); held-out/contamination is derived per model afterwards.
The bundle's suite content_hash pins the exact set, so runs are comparable iff (level, version) +
content_hash match.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .challenges import filter_challenges

LEVELS_PATH = Path(os.environ.get("PEAKSTONE_LEVELS") or Path(__file__).resolve().parent / "levels.toml")

# Axes that need a specific model capability to be meaningful. Coding/math/safety are plain chat and
# any instruct model attempts them; only tool-use and repo-level agentic genuinely gate participation.
GATED_CAP = {"tool-calling": "tools", "injection": "tools", "swebench": "agentic", "env": "agentic"}
def model_capabilities(model_name: str, models_toml: Path | None = None) -> set[str]:
    """A model's effective capabilities, resolved by engine.capabilities
    (declared > probed/observed cache > inferred-from-ctx). Kept here as the name relevance imports."""
    from . import capabilities
    return capabilities.effective_capabilities(model_name, models_toml=models_toml)


def relevant(family: str, capabilities) -> bool:
    """Whether a model with these capabilities should attempt this family's axis."""
    cap = GATED_CAP.get(family)
    return cap is None or cap in (capabilities or set())


@dataclass
class Level:
    name: str
    description: str = ""
    time_hint: str = ""
    judge: bool = False
    agent: bool = False
    prebuilt: bool = False
    retries: int = 0
    calibration: bool = False
    select: list[dict] = field(default_factory=list)


def load_levels(path: Path | None = None) -> tuple[str, dict[str, Level]]:
    data = tomllib.loads((path or LEVELS_PATH).read_text())
    version = str(data.pop("version", "unversioned"))
    levels: dict[str, Level] = {}
    for name, d in data.items():
        if not isinstance(d, dict):
            continue
        levels[name] = Level(
            name=name, description=d.get("description", ""), time_hint=d.get("time_hint", ""),
            judge=bool(d.get("judge", False)), agent=bool(d.get("agent", False)),
            prebuilt=bool(d.get("prebuilt", False)), retries=int(d.get("retries", 0)),
            calibration=bool(d.get("calibration", False)),
            select=list(d.get("select", [])))
    return version, levels


def resolve(level: Level, challenges) -> list[str]:
    """Deterministic, ordered, unique challenge ids selected by this level against the corpus.

    Each axis: filter by family/difficulty, then take `limit`. When an axis is **capped** by `limit`,
    the NEWEST challenges win — sort by `published_at` descending (id breaks ties) before truncating —
    so a limited dated family (livecodebench/codeforces/…) contributes its most recent, least-
    contaminated problems and maximizes held-out coverage for recently-released models. Uncapped axes
    keep id order. Selection stays model-INDEPENDENT and content-pinned (publish dates are fixed
    challenge content), so the resulting content_hash is still reproducible across models/quants."""
    out: list[str] = []
    seen: set[str] = set()
    for sel in level.select:
        fam = sel.get("family")
        diffs = sel.get("difficulty")
        matched = filter_challenges(
            challenges,
            families=[fam] if fam else None,
            difficulties=[int(x) for x in diffs] if diffs else None,
        )
        matched.sort(key=lambda c: c.id)
        if sel.get("limit"):
            # newest-first when capping (stable, so id order breaks date ties; undated sort last),
            # then restore id order for a stable run sequence (content_hash is order-independent).
            matched.sort(key=lambda c: c.published_at or "", reverse=True)
            matched = matched[: int(sel["limit"])]
            matched.sort(key=lambda c: c.id)
        for c in matched:
            if c.id not in seen:
                seen.add(c.id)
                out.append(c.id)
    return out

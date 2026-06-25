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


@dataclass
class Level:
    name: str
    description: str = ""
    time_hint: str = ""
    judge: bool = False
    agent: bool = False
    prebuilt: bool = False
    retries: int = 0
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
            select=list(d.get("select", [])))
    return version, levels


def resolve(level: Level, challenges) -> list[str]:
    """Deterministic, ordered, unique challenge ids selected by this level against the corpus.
    Each axis: filter by family/difficulty, sort by id, take first `limit`. Order = axis order in
    the manifest, then id — so the resulting content_hash is reproducible across runs."""
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
            matched = matched[: int(sel["limit"])]
        for c in matched:
            if c.id not in seen:
                seen.add(c.id)
                out.append(c.id)
    return out

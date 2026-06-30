"""Browse & select peakstones by family and date for the TUI.

Pure data layer (no Textual imports) so the grouping + selection logic is unit-testable without a
terminal. The screen in app.py renders these groupings as a tree and drives a Selection.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..engine import paths
from ..engine.challenges import Challenge, load_challenges

UNDATED = "undated"

# Families produced by the public-suite importers. Everything else is hand-authored here ("native"),
# so the menu can collapse all native families under one collection while each imported suite stays
# its own top-level group. Keep in sync with peakstone/engine/importers/.
IMPORTED_SUITES = {"humaneval", "bigcodebench", "livecodebench", "codeforces", "aime", "swebench"}
NATIVE_LABEL = "Peakstone"   # our own (hand-authored) collection; imported public suites stay separate


def load_corpus() -> list[Challenge]:
    """All active challenges in the corpus (same loader the runner uses)."""
    return load_challenges(paths.challenges_dir())


def date_bucket(ch: Challenge) -> str:
    """YYYY-MM bucket from published_at, or 'undated' when the date is missing/malformed."""
    d = (ch.published_at or "")[:7]
    return d if (len(d) == 7 and d[4] == "-") else UNDATED


def group_by_family(chs: list[Challenge]) -> dict[str, list[Challenge]]:
    """{family: challenges}, largest family first (so big suites lead the menu)."""
    out: dict[str, list[Challenge]] = defaultdict(list)
    for c in chs:
        out[c.family].append(c)
    return dict(sorted(out.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def group_by_date(chs: list[Challenge]) -> dict[str, list[Challenge]]:
    """{YYYY-MM: challenges}, chronological, 'undated' last."""
    out: dict[str, list[Challenge]] = defaultdict(list)
    for c in chs:
        out[date_bucket(c)].append(c)
    return dict(sorted(out.items(), key=lambda kv: (kv[0] == UNDATED, kv[0])))


SOLVES_PER_SEC = 1.0   # nominal solve rate for the menu's at-a-glance ETA (model-independent)


def rough_eta(n: int, per_sec: float = SOLVES_PER_SEC) -> str:
    """Very rough wall-clock for n peakstones at a nominal solve rate — a size proxy for quick
    overview only, not a real run estimate (engine.estimate has the model-aware version)."""
    if n <= 0:
        return ""
    secs = n / per_sec
    if secs < 90:
        return f"~{secs:.0f}s"
    if secs < 5400:
        return f"~{secs / 60:.0f}m"
    return f"~{secs / 3600:.1f}h"


def is_native(ch: Challenge) -> bool:
    """A peakstone we authored (vs imported from a public suite)."""
    return ch.family not in IMPORTED_SUITES


def date_span(chs: list[Challenge]) -> str:
    """Compact date caption for a group: '2026-07' if all share one month, '2024-08…2025-02' for a
    range, '' when undated. Captions a collection node."""
    months = sorted({b for c in chs if (b := date_bucket(c)) != UNDATED})
    if not months:
        return ""
    return months[0] if len(months) == 1 else f"{months[0]}…{months[-1]}"


def group_by_collection(chs: list[Challenge]) -> list[dict]:
    """Top-level menu grouping. Native peakstones collapse into one collection (with language/axis
    families beneath); each imported public suite is its own collection. Returns ordered dicts
    {kind: 'native'|'suite', label, chs} — native first, then suites largest-first."""
    native = [c for c in chs if is_native(c)]
    imported = [c for c in chs if not is_native(c)]
    groups: list[dict] = []
    if native:
        groups.append({"kind": "native", "label": NATIVE_LABEL, "chs": native})
    for fam, fchs in group_by_family(imported).items():
        groups.append({"kind": "suite", "label": fam, "chs": fchs})
    return groups


@dataclass
class Selection:
    """A mutable set of selected challenge ids. Toggling a group of ids is all-or-nothing: if every
    id in the group is already selected it deselects them, otherwise it selects the whole group —
    so a family/date node behaves like a checkbox over its descendants."""
    ids: set[str] = field(default_factory=set)

    def toggle(self, ids) -> None:
        ids = set(ids)
        if ids and ids <= self.ids:
            self.ids -= ids
        else:
            self.ids |= ids

    def state(self, ids) -> str:
        """'all' | 'some' | 'none' for a group — drives the ✓/◐/blank marker."""
        ids = set(ids)
        if not ids:
            return "none"
        inter = ids & self.ids
        if inter == ids:
            return "all"
        return "some" if inter else "none"

    def resolve(self) -> list[str]:
        return sorted(self.ids)


MARKER = {"all": "✓", "some": "◐", "none": " "}

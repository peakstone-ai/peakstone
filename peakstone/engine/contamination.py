"""Contamination status — the spine of the timeline/evolution feature.

A model cannot have trained on a challenge published after the model was released, so a score
on such a challenge is *held-out*: real generalization, not memorization. This module turns
that one idea into a deterministic status on every (model, challenge) pair and an aggregate
the leaderboard leads with.

Design choices (see also the schema descriptions):
  * The boundary is the model's `release_date` — public and UNFORGEABLE. `training_cutoff` is
    tighter but self-reported, so it backs only a secondary "claimed-clean" view (pass
    boundary=training_cutoff to opt in). The official held-out score uses release_date.
  * Status is DERIVED from raw dates stored in the bundle, never frozen into it — so it
    recomputes as date knowledge improves (e.g. the platform's first-seen timestamp lands).
  * Honesty over coverage: a missing/unparseable date on either side yields UNKNOWN, never a
    silent "clean". The size of the unknown bucket is reported, not hidden.

This is intentionally dependency-free and pure so it runs identically in the engine, the API,
and tests.
"""
from __future__ import annotations

from dataclasses import dataclass

CLEAN = "clean"            # published strictly after the boundary -> uncontaminated
CONTAMINATED = "contaminated"  # published on/before the boundary -> may be in training data
UNKNOWN = "unknown"        # a date is missing/unparseable on one side -> undecidable


def _as_date(s) -> str | None:
    """Normalize a date-ish value to a comparable 'YYYY-MM-DD' string, or None if unusable.
    ISO date and date-time both work (lexicographic order on the 10-char prefix is chronological)."""
    if not s or not isinstance(s, str):
        return None
    d = s.strip()[:10]
    if len(d) != 10 or d[4] != "-" or d[7] != "-":
        return None
    y, m, day = d[:4], d[5:7], d[8:10]
    if not (y.isdigit() and m.isdigit() and day.isdigit()):
        return None
    return d


def clean(published_at, boundary) -> str:
    """Contamination status of one result. CLEAN iff the challenge was published strictly after
    the boundary date (the model's release_date). UNKNOWN if either date is missing/unparseable."""
    p, b = _as_date(published_at), _as_date(boundary)
    if p is None or b is None:
        return UNKNOWN
    return CLEAN if p > b else CONTAMINATED


@dataclass
class HeldOut:
    score: float | None      # mean final score over CLEAN results; None if there are none
    n_clean: int
    n_contaminated: int
    n_unknown: int
    boundary: str | None     # the date used as the cutoff (release_date), normalized

    @property
    def coverage(self) -> float:
        """Fraction of results whose contamination status is decided (not unknown)."""
        total = self.n_clean + self.n_contaminated + self.n_unknown
        return (total - self.n_unknown) / total if total else 0.0


def held_out_score(results, boundary) -> HeldOut:
    """The headline metric: mean `score.final` over challenges published after `boundary`
    (a model's release_date). `results` are bundle result dicts (each with `published_at` and
    `score.final`). Contaminated and unknown results are counted but excluded from the score."""
    b = _as_date(boundary)
    n_clean = n_cont = n_unknown = 0
    total = 0.0
    for r in results:
        status = clean(r.get("published_at"), b)
        if status == CLEAN:
            n_clean += 1
            total += float((r.get("score") or {}).get("final", 0.0))
        elif status == CONTAMINATED:
            n_cont += 1
        else:
            n_unknown += 1
    return HeldOut(
        score=(total / n_clean) if n_clean else None,
        n_clean=n_clean, n_contaminated=n_cont, n_unknown=n_unknown, boundary=b,
    )

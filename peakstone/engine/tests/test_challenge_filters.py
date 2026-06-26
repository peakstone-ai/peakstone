"""Family/date selectors on filter_challenges + the Challenge.family property."""
from __future__ import annotations

from pathlib import Path

from peakstone.engine.challenges import Challenge, filter_challenges


def _ch(cid: str, family: str, published_at: str = "", min_ctx: int = 0) -> Challenge:
    # family is derived from dir.parent.name, so place the challenge under challenges/<family>/<cid>
    return Challenge(
        id=cid, title=cid, language="python", difficulty=1, category="code-correctness",
        scoring="tests", solution_file="solution.py", timeout=30,
        dir=Path(f"challenges/{family}/{cid}"), spec="", published_at=published_at, min_ctx=min_ctx,
    )


CHS = [
    _ch("he-000", "humaneval", "2021-07-07"),
    _ch("lcb-a", "livecodebench", "2025-01-04"),
    _ch("lcb-b", "livecodebench", "2025-03-22"),
    _ch("py-1", "python", ""),            # native, undated
]


def test_family_property():
    assert _ch("x", "livecodebench").family == "livecodebench"


def test_filter_by_family():
    out = {c.id for c in filter_challenges(CHS, families=["livecodebench"])}
    assert out == {"lcb-a", "lcb-b"}
    out2 = {c.id for c in filter_challenges(CHS, families=["humaneval", "python"])}
    assert out2 == {"he-000", "py-1"}


def test_published_after_excludes_older_and_undated():
    out = {c.id for c in filter_challenges(CHS, published_after="2025-02-19")}
    assert out == {"lcb-b"}                      # lcb-a (Jan) and undated py-1 excluded


def test_published_before():
    out = {c.id for c in filter_challenges(CHS, published_before="2025-02-01")}
    assert out == {"he-000", "lcb-a"}            # undated still excluded under a date bound


def test_family_and_date_compose():
    out = {c.id for c in filter_challenges(CHS, families=["livecodebench"],
                                           published_after="2025-02-19")}
    assert out == {"lcb-b"}


def test_no_date_filter_keeps_undated():
    out = {c.id for c in filter_challenges(CHS, families=["python"])}
    assert out == {"py-1"}                       # no date bound -> undated kept


def test_served_ctx_gates_long_context():
    chs = [_ch("plain", "python"), _ch("lc-big", "longcontext", min_ctx=16384)]
    # served window too small -> the long-context challenge is dropped (would only truncate + fail)
    assert {c.id for c in filter_challenges(chs, served_ctx=8192)} == {"plain"}
    # window large enough -> both kept
    assert {c.id for c in filter_challenges(chs, served_ctx=16384)} == {"plain", "lc-big"}
    # no served_ctx given (e.g. reference run) -> no ctx gating
    assert {c.id for c in filter_challenges(chs)} == {"plain", "lc-big"}

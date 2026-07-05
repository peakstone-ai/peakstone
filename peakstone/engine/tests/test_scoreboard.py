"""engine.scoreboard: axis assignment, sealed-private handling, budget parsing, summarize shape."""
from __future__ import annotations

from peakstone.engine import scoreboard as sb


def _r(cid="c", final=1.0, category="basic", verification="deterministic-tests", **extra):
    return {"challenge_id": cid, "category": category, "verification": verification,
            "score": {"final": final, "passed": int(final), "total": 1}, **extra}


def test_axis_of_ordering():
    # goal-state-env wins over category
    assert sb.axis_of(_r(category="basic", verification="goal-state-env")) == "agentic"
    assert sb.axis_of(_r(category="planner")) == "planner"
    assert sb.axis_of(_r(category="math")) == "math"
    assert sb.axis_of(_r(category="long-context")) == "long-context"
    assert sb.axis_of(_r(category="refusal")) == "safety"
    assert sb.axis_of(_r(category="basic")) == "code"


def test_reasoning_budget_from_flags():
    assert sb.reasoning_budget_from_flags("-fa on --reasoning-budget 0") == 0
    assert sb.reasoning_budget_from_flags("--reasoning-budget -1 --ctx 8k") == -1
    assert sb.reasoning_budget_from_flags("--reasoning-budget 4096") == 4096
    assert sb.reasoning_budget_from_flags("-ngl 99") is None
    assert sb.reasoning_budget_from_flags(None) is None


def test_summarize_axis_partition():
    rows = [_r("a", 1.0, "basic"), _r("b", 0.0, "basic"),
            _r("m1", 0.5, "math"), _r("s1", 1.0, "injection"),
            _r("e1", 1.0, "basic", verification="goal-state-env"),
            _r("p1", 0.75, "planner"), _r("lc", 0.25, "long-context")]
    s = sb.summarize_rows(rows)
    assert s["code_score"] == 0.5 and s["n_code"] == 2 and s["solved"] == 1
    assert s["math_score"] == 0.5 and s["safety_score"] == 1.0
    assert s["agent_score"] == 1.0 and s["n_agent"] == 1
    assert s["planner_score"] == 0.75 and s["long_ctx_score"] == 0.25
    assert s["n_total"] == 7


def test_sealed_private_earns_no_credit():
    rows = [_r("a", 0.5, "basic"),
            _r("p", 1.0, "basic", private=True),                 # sealed → excluded
            _r("q", 1.0, "basic", private=True, revealed=True)]  # revealed → counts
    s = sb.summarize_rows(rows)
    assert s["code_score"] == 0.75           # (0.5 + 1.0) / 2, sealed 1.0 dropped
    assert s["n_committed"] == 2 and s["n_revealed"] == 1
    assert s["n_total"] == 2                  # only credited rows


def test_held_out_uses_release_date():
    rows = [_r("old", 1.0, "basic", published_at="2020-01-01"),
            _r("new", 0.0, "basic", published_at="2030-01-01")]
    s = sb.summarize_rows(rows, release_date="2025-01-01")
    assert s["code_score"] == 0.5                 # both count for the raw score
    assert s["held_out_score"] == 0.0             # only the post-release (2030) challenge is held-out
    assert s["held_out"]["n_clean"] == 1


def test_empty_run():
    s = sb.summarize_rows([])
    assert s["code_score"] is None and s["n_total"] == 0 and s["by_category"] == {}

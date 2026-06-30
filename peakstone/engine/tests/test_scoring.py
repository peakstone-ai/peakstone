"""compute_score: a flaky judge must not be scored as a real 0.0 (review should-fix)."""
from types import SimpleNamespace

from peakstone.engine.scoring import compute_score


def _ch(scoring, weight=0.5):
    return SimpleNamespace(scoring=scoring, judge_weight=weight)


def _run(pass_rate):
    return SimpleNamespace(pass_rate=pass_rate, passed=int(pass_rate * 10), total=10, extra={})


_OK_JUDGE = {"scores": {"quality": 8}, "normalized": 0.8}
_FLAKY_JUDGE = {"error": "unparseable judge output", "scores": {}, "normalized": 0.0}


def test_flaky_judge_falls_back_to_tests():
    # judge-scored: a passing solution must not be zeroed because the local judge timed out
    assert compute_score(_ch("judge"), _run(1.0), _FLAKY_JUDGE)["final_score"] == 1.0
    # both-scored: fall back to tests only, no spurious 0.0 judge component
    assert compute_score(_ch("both"), _run(1.0), _FLAKY_JUDGE)["final_score"] == 1.0


def test_real_judge_still_counts():
    assert compute_score(_ch("judge"), _run(0.0), _OK_JUDGE)["final_score"] == 0.8
    # a genuine low judge score (no error) still penalises, as intended
    assert compute_score(_ch("judge"), _run(1.0), {"scores": {"q": 0}, "normalized": 0.0})["final_score"] == 0.0
    # both = weighted blend
    assert compute_score(_ch("both", 0.5), _run(1.0), _OK_JUDGE)["final_score"] == 0.9


def test_no_judge_falls_back_to_tests():
    assert compute_score(_ch("judge"), _run(0.7), None)["final_score"] == 0.7
    assert compute_score(_ch("both"), _run(0.7), None)["final_score"] == 0.7

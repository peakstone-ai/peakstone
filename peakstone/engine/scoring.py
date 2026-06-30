"""Combine test pass-rate and (optional) judge score into a final 0-1 score."""
from __future__ import annotations


def _judge_ran(jr) -> bool:
    """True only if the judge actually produced scores. A flaky/unparseable judge (timeout, bad JSON)
    returns {"error":..., "scores":{}, "normalized":0.0}; folding that in as a real 0.0 would punish a
    passing solution for the LOCAL JUDGE's flakiness instead of the model's quality, making leaderboard
    numbers wobble run-to-run on judge noise. Treat it as 'no judge ran' and fall back to tests."""
    return bool(jr) and not jr.get("error") and bool(jr.get("scores"))


def compute_score(challenge, run_result, judge_result) -> dict:
    test_score = run_result.pass_rate  # 0..1
    judge_norm = (judge_result or {}).get("normalized", 0.0)
    judge_ran = _judge_ran(judge_result)

    if challenge.scoring == "tests":
        final = test_score
    elif challenge.scoring == "judge":
        # No judge ran (--reference/--no-judge) OR the judge flaked: fall back to tests.
        final = judge_norm if judge_ran else test_score
    else:  # both
        if not judge_ran:
            # Judge disabled or flaked: score on tests only rather than penalizing for the
            # absent/failed (0.0) judge component.
            final = test_score
        else:
            w = challenge.judge_weight
            final = (1 - w) * test_score + w * judge_norm

    # small bonus signal: TS typecheck (does not change final, recorded for the report)
    typecheck = run_result.extra.get("typecheck_ok")
    return {
        "test_score": round(test_score, 3),
        "judge_score": round(judge_norm, 3),
        "final_score": round(final, 3),
        "passed": run_result.passed,
        "total": run_result.total,
        "typecheck_ok": typecheck,
    }

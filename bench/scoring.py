"""Combine test pass-rate and (optional) judge score into a final 0-1 score."""
from __future__ import annotations


def compute_score(challenge, run_result, judge_result) -> dict:
    test_score = run_result.pass_rate  # 0..1
    judge_norm = (judge_result or {}).get("normalized", 0.0)

    if challenge.scoring == "tests":
        final = test_score
    elif challenge.scoring == "judge":
        # No judge ran (e.g. --reference / --no-judge): fall back to tests.
        final = judge_norm if judge_result is not None else test_score
    else:  # both
        if judge_result is None:
            # Judge disabled: score on tests only rather than penalizing for the
            # absent (0.0) judge component.
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

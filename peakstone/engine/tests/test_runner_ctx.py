"""Served-context resolution used to gate long-context challenges per run."""
from __future__ import annotations

from peakstone.engine import runner


def test_served_ctx_env_override(monkeypatch):
    monkeypatch.setenv("PEAKSTONE_CTX", "8192")
    assert runner._served_ctx("any-model") == 8192   # PEAKSTONE_CTX overrides the registry ctx


def test_served_ctx_unknown_model_is_none(monkeypatch):
    monkeypatch.delenv("PEAKSTONE_CTX", raising=False)
    assert runner._served_ctx("definitely-not-a-registered-model") is None


def _feed(outcomes, threshold=3):
    """Replay (won, looped) outcomes for one category through the streak policy; return the abandon
    step (1-based) or None, plus the final abandoned set."""
    streaks, passed, abandoned = {}, set(), set()
    abandon_at = None
    for i, (won, looped) in enumerate(outcomes, 1):
        if runner.update_loop_streak("fam", won=won, looped=looped, streaks=streaks,
                                     passed=passed, abandoned=abandoned, threshold=threshold):
            abandon_at = abandon_at or i
    return abandon_at, abandoned


def test_three_consecutive_loops_abandon_category():
    abandon_at, abandoned = _feed([(False, True)] * 3)
    assert abandon_at == 3 and abandoned == {"fam"}


def test_two_loops_do_not_abandon():
    abandon_at, abandoned = _feed([(False, True), (False, True)])
    assert abandon_at is None and abandoned == set()


def test_non_loop_failure_breaks_the_streak():
    # loop, loop, plain-fail (resets), loop, loop — never 3 in a row → no abandon
    abandon_at, _ = _feed([(False, True), (False, True), (False, False),
                           (False, True), (False, True)])
    assert abandon_at is None


def test_a_pass_immunizes_the_category():
    # two loops, a pass (clears + immunizes), then three more loops — still not abandoned
    abandon_at, _ = _feed([(False, True), (False, True), (True, False),
                           (False, True), (False, True), (False, True)])
    assert abandon_at is None


def test_retry_attempt_without_reasoning_validates():
    """Regression: a self-repair attempt from a model with no CoT channel (reasoning None/omitted) must
    still produce a valid bundle — it was failing the whole run on a schema ValidationError."""
    from peakstone.engine import bundle as B
    meta = {"timestamp": "t", "models": ["m"], "judge": None, "gpu": None, "mem_used": {}}
    row = {"model": "m", "challenge": "c1", "language": "py", "difficulty": 1, "category": "code",
           "type": "code", "scoring": "tests", "final_score": 1.0, "passed": 3, "total": 3,
           "response": "ok",
           "attempts_log": [{"answer": "def f(): return 2", "passed": 0, "total": 3, "test_error": "boom"},
                            {"answer": "def f(): return 1", "passed": 3, "total": 3, "test_error": ""}]}
    b = B.produce_bundle(meta, [row], sign=False)          # must not raise
    atts = b["results"][0]["transcript"]["attempts"]
    assert len(atts) == 2 and atts[0].get("reasoning") is None   # omitted, run still valid


def test_metacog_segment():
    # no calibration → nothing shown
    assert runner._metacog(None, None, True) == ""
    # pre-hoc confidence only
    assert "can 0.80" in runner._metacog(0.8, None, True)
    # post-hoc self-verdict vs reality: the three calibration outcomes
    assert "did:yes (knew)" in runner._metacog(0.9, True, True)          # said correct, passed
    assert "did:yes (overconfident)" in runner._metacog(0.9, True, False)  # said correct, failed
    assert "did:no (underrated)" in runner._metacog(0.1, False, True)    # said wrong, passed
    assert "did:no (knew)" in runner._metacog(0.1, False, False)         # said wrong, failed


def test_bundle_records_seed_and_stack():
    """Reproducibility: the fixed seed (config [run].seed) lands in sampling, and the run documents its
    stack (python/os) + a coarse contention snapshot (host_load) for attributing perf shifts."""
    from peakstone.engine import bundle as B
    res = [{"model": "m", "challenge": "c1", "language": "py", "difficulty": 1, "category": "code",
            "type": "code", "scoring": "tests", "final_score": 1.0, "passed": 3, "total": 3,
            "response": "x"}]
    b = B.produce_bundle({"timestamp": "t", "models": ["m"], "judge": None, "gpu": None,
                          "mem_used": {}, "host_load": {"load_avg_1m": 0.5, "gpu_procs": 1}},
                         res, sign=False)
    assert "seed" in b["model"]["sampling"]                 # seed captured (config default 42)
    assert b["environment"].get("python") and b["environment"].get("os")
    assert b["environment"]["host_load"] == {"load_avg_1m": 0.5, "gpu_procs": 1}


def test_not_capable_bundle_validates():
    from peakstone.engine import bundle as B
    meta = {"timestamp": "t", "models": ["m"], "judge": None, "gpu": None, "mem_used": {},
            "run_status": "not_capable", "abandoned_categories": ["python", "go"],
            "run_verdict": {"reason": "repetition_loops",
                            "abandoned_categories": ["python", "go"], "loop_streak": 3}}
    results = [{"model": "m", "challenge": "c1", "language": "py", "difficulty": 1, "category": "code",
                "type": "code", "scoring": "tests", "final_score": 0.0, "test_score": 0.0,
                "passed": 0, "total": 3, "response": "x", "error": "repetition-loop"}]
    b = B.produce_bundle(meta, results, sign=False)
    assert b["run_status"] == "not_capable" and b["abandoned_categories"] == ["python", "go"]


def test_multi_model_bundle_refused():
    """A bundle is signed + attributed to ONE model; --bundle with >1 model must refuse up front
    (else the other models' results get mis-attributed to models[0]). Review finding M7."""
    assert runner.main(["--models", "a,b", "--bundle", "--no-judge"]) == 2
    # single-model --bundle is the normal path and is NOT blocked by this guard

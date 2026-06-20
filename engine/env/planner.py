"""Planner-agent as an env type (PLAN.md §9 P3).

A planner challenge evaluates a model's ability to *plan*, not to code: the planner model writes an
implementation plan for a task, a FIXED coder model executes that plan, and the goal state is the
coder's solution passing the task's tests. This folds the P2 planner eval into the agentic
framework, so planning surfaces as its own `planner_score` axis alongside coder/agentic — distinct
from raw coding ability (the same coder executing every plan isolates the *plan's* contribution).

Reuses the regular coding challenges (spec + tests + reference): the plan→code→test pipeline IS the
goal-state evaluation. Both clients are pluggable (so it's testable with stubs, and a planner can be
scored against any fixed coder).
"""
from __future__ import annotations

from .. import extract, sandbox, scoring


def generate_plan(planner_client, planner_model, challenge, *, max_tokens=2048, timeout=120) -> dict:
    from ..runner import PLAN_SYSTEM
    res = planner_client.chat(
        planner_model,
        [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": challenge.spec}],
        temperature=0.2, max_tokens=max_tokens, timeout=timeout)
    return {"plan": res.text or "", "latency_s": res.latency_s, "tokens": res.completion_tokens,
            "error": res.error}


def execute_plan(coder_client, coder_model, challenge, plan, cfg, *, max_tokens=4096, timeout=120) -> dict:
    from ..runner import SYSTEM_PROMPT
    prompt = challenge.spec + "\n\n## Implementation plan\n" + plan
    res = coder_client.chat(
        coder_model,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        temperature=0.2, max_tokens=max_tokens, timeout=timeout)
    files = extract.extract_files(res.text or "", challenge.solution_file, challenge.language)
    run = sandbox.run_tests(challenge, files, cfg)
    sc = scoring.compute_score(challenge, run, None)
    return {"response": res.text or "", "run": run, "score": sc, "latency_s": res.latency_s}


def run_planner_task(planner_client, planner_model, coder_client, coder_model, challenge, cfg) -> dict:
    """Plan → fixed coder executes → tests. Returns the downstream score (the planner's lift)."""
    p = generate_plan(planner_client, planner_model, challenge)
    if p.get("error") or not p["plan"].strip():
        return {"passed": False, "final_score": 0.0, "passed_n": 0, "total": 0, "plan": "",
                "plan_chars": 0, "planner_latency_s": p.get("latency_s"), "coder_model": coder_model,
                "downstream_score": 0.0, "error": p.get("error") or "empty plan"}
    e = execute_plan(coder_client, coder_model, challenge, p["plan"], cfg)
    sc = e["score"]
    return {
        "passed": bool(e["run"].ok),
        "final_score": sc["final_score"], "passed_n": sc["passed"], "total": sc["total"],
        "plan": p["plan"], "plan_chars": len(p["plan"]), "planner_latency_s": p["latency_s"],
        "coder_model": coder_model, "downstream_score": sc["final_score"],
        "response": e["response"], "stdout": (e["run"].stdout or "")[-2000:],
    }


def planner_result_row(challenge, result, planner_model) -> dict:
    """A bundle result row for a planner run — category 'planner' so the API scores it on its own
    axis, with the plan + fixed coder recorded for provenance."""
    return {
        "model": planner_model, "challenge": challenge.id, "language": challenge.language,
        "category": "planner", "type": "planner", "difficulty": challenge.difficulty,
        "scoring": "tests", "verification": "deterministic-tests",
        "final_score": result["final_score"], "passed": result["passed_n"], "total": result["total"],
        "response": result.get("response", ""), "stdout": result.get("stdout", ""),
        "planner_response": result.get("plan", ""),
        "env": {"role": "planner", "coder_model": result["coder_model"],
                "plan_chars": result["plan_chars"], "planner_latency_s": result["planner_latency_s"],
                "downstream_score": result["downstream_score"]},
    }

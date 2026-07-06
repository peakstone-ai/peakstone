"""Shared leaderboard axis math — ONE definition of how result rows become scores.

Operates on bundle-shaped row DICTS (what `bundle.json["results"]` contains: `score.final`,
`category`, `verification`, `published_at`, `metrics`, `private`/`revealed`, …). Three consumers:
the API's `_summarize` (ORM rows adapted to dicts), the TUI's offline local board
(dashboard/localboard.py, straight from bundle files), and `peakstone check`'s axis split — so a
local score, a server score, and a CI verdict can never disagree about what an axis means.

Extracted verbatim from api/main.py (2026-07); every `round()` is part of the contract (the API's
exact-value tests gate byte-parity).
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import contamination

# Capability categories that are safety/honesty, not coding ability — scored separately so a strong
# coder isn't penalised (or flattered) in the headline code score (mirrors the report's split).
SAFETY = {"injection", "refusal", "hallucination", "security", "secure-code"}

# No-LLM efficiency axes (engine/metrics.py). "asc" = smaller-is-better. Sortable on the leaderboard
# alongside code_score; a model can be correct-but-bloated vs correct-and-lean.
METRIC_AXES = {"peak_rss_mb": "asc", "loc": "asc", "solution_bytes": "asc", "test_wall_s": "asc"}
# All sortable leaderboard keys → default order. held_out_score (contamination-adjusted code
# score) is the headline timeline metric; ranking by it drops models with no release_date or no
# post-release challenges (held_out_score=None → they don't qualify for that board).
SORT_ORDER = {"code_score": "desc", "held_out_score": "desc", "math_score": "desc",
              "agent_score": "desc", "planner_score": "desc", "safety_score": "desc",
              "solved": "desc", "tok_per_s": "desc", "sol_per_s": "desc", "n_total": "desc",
              "total_time_s": "asc",                  # quicker runs rank first
              "score_per_1k_tokens": "desc",          # context-efficiency: capability per token
              "tokens_to_solve": "asc", "gen_tokens": "asc",
              "long_ctx_score": "desc",               # long-context comprehension axis
              "self_verify_accuracy": "desc",          # calibration: does it know when it's right?
              "confidence_score": "desc",              # calibration: pre-hoc confidence vs outcome
              "recovery_rate": "desc",                 # self-repair: fixes its own first-try failures
              "truncation_rate": "asc",                # budget-fit: lower = less often cut off mid-thought
              **METRIC_AXES}

# token-efficiency keys live in result.metrics but are summarized specially (honest, ctx-limited-aware)
# in _ctx_efficiency — keep them out of the generic leanness aggregate so each is reported once.
_TOKEN_KEYS = {"gen_tokens", "prompt_tokens", "tokens_to_solve", "ctx_limited", "reasoning_tokens"}


def _final(r: dict) -> float:
    return float((r.get("score") or {}).get("final", 0.0))


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def sort_value(row: dict, key: str):
    if key in row:
        return row.get(key)
    return (row.get("metrics") or {}).get(key)


def reasoning_budget_from_flags(serve_flags: str | None) -> int | None:
    """The thinking budget a run was SERVED at, from `--reasoning-budget N` in the serve flags:
    0 = off, -1 = full (unlimited), N = capped at N thinking tokens. None if the flag wasn't set."""
    m = re.search(r"--reasoning-budget\s+(-?\d+)", serve_flags or "")
    return int(m.group(1)) if m else None


def axis_of(r: dict) -> str:
    """The leaderboard axis a result row belongs to. Order matters: goal-state-env beats category."""
    cat = r.get("category") or ""
    if (r.get("verification") or "") == "goal-state-env":
        return "agentic"
    if cat == "planner":
        return "planner"
    if cat == "math":
        return "math"
    if cat == "long-context":
        return "long-context"
    if cat in SAFETY:
        return "safety"
    return "code"


def _agg_metrics(rs) -> dict:
    """Average each efficiency metric over the results that recorded it (the run's leanness)."""
    buckets: dict[str, list] = defaultdict(list)
    for r in rs:
        for k, v in (r.get("metrics") or {}).items():
            # cal_*/repair_*/trunc_* are calibration, self-repair & truncation probes, summarized
            # specially below (not leanness/efficiency axes)
            if (k not in _TOKEN_KEYS and not k.startswith(("cal_", "repair_", "trunc_"))
                    and isinstance(v, (int, float))):
                buckets[k].append(v)
    return {k: round(sum(v) / len(v), 2) for k, v in buckets.items() if v}


def _calibration(rs) -> dict:
    """Metacognition over results carrying calibration probes (the `cal_*` metric keys). Two numbers,
    both higher=better, computed only over the probed challenges:
      * self_verify_accuracy — how often the model's POST-hoc 'is my solution correct?' matched the
        actual test outcome (knowing when you're right is the bedrock of agentic reliability);
      * confidence_score — 1 − Brier over the PRE-hoc 'will I solve this?' probability vs the outcome
        (a perfectly calibrated forecaster scores 1.0; constant-0.5 guessing scores 0.75)."""
    sv_n = sv_hit = br_n = 0
    br_sum = 0.0
    for r in rs:
        m = r.get("metrics") or {}
        passed = 1.0 if _final(r) >= 0.999 else 0.0
        if "cal_self_correct" in m:
            sv_n += 1
            if (1.0 if m["cal_self_correct"] >= 0.5 else 0.0) == passed:
                sv_hit += 1
        if "cal_pre_confidence" in m:
            br_n += 1
            br_sum += (float(m["cal_pre_confidence"]) - passed) ** 2
    return {
        "self_verify_accuracy": round(sv_hit / sv_n, 3) if sv_n else None,
        "confidence_score": round(1 - br_sum / br_n, 3) if br_n else None,
        "n_calibration": max(sv_n, br_n),
    }


def _self_repair(rs) -> dict:
    """Self-repair (isolated from the headline, which is first-try): of the coding challenges a model
    failed on its FIRST attempt, what fraction did it fix when shown the test error (--retries)?
    recovery_rate in [0,1] (higher = better debugger); n_repair = the first-try failures it was probed
    on. The headline code/held-out scores stay single-shot — this is the separate debugging axis."""
    vals = [r["metrics"]["repair_recovered"] for r in rs
            if r.get("metrics") and "repair_recovered" in r["metrics"]]
    return {
        "recovery_rate": round(sum(vals) / len(vals), 3) if vals else None,
        "n_repair": len(vals),
    }


def _truncation(rs) -> dict:
    """How often generation hit the token budget (max_tokens) instead of finishing on its own — i.e.
    the model was likely cut off mid-thought. Token-bound, so it's hardware-independent and fully
    reproducible; but a high rate is a WARNING that the budget is too tight to fairly measure this
    model's capability (its score is budget-limited, not ability-limited). Lower is better."""
    vals = [r["metrics"]["trunc_truncated"] for r in rs
            if r.get("metrics") and "trunc_truncated" in r["metrics"]]
    return {
        "truncation_rate": round(sum(vals) / len(vals), 3) if vals else None,
        "n_generated": len(vals),
    }


def _ctx_efficiency(code_rs) -> dict:
    """Context-efficiency over code results. Excludes ctx-limited results (whose token counts are
    censored and scores depressed by window truncation, not capability) so the numbers are honest
    like-for-like. Tokens are model-native — compare within a family/tokenizer (quant/ctx), not across
    families. score_per_1k_tokens = mean code score per 1k tokens spent (capability per token)."""
    measured = [r for r in code_rs if (r.get("metrics") or {}).get("tokens_to_solve")]
    n_ctx_limited = sum(1 for r in measured if (r.get("metrics") or {}).get("ctx_limited"))
    eff = [r for r in measured if not (r.get("metrics") or {}).get("ctx_limited")]
    if not eff:
        return {"score_per_1k_tokens": None, "tokens_to_solve": None, "gen_tokens": None,
                "reasoning_tokens": None, "n_ctx_limited": n_ctx_limited}

    def _mean(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return (sum(vals) / len(vals)) if vals else None

    mean_tts = _mean([r["metrics"].get("tokens_to_solve") for r in eff])
    mean_final = sum(_final(r) for r in eff) / len(eff)
    rea = _mean([r["metrics"].get("reasoning_tokens") for r in eff])    # None when the server never reported it
    return {
        "score_per_1k_tokens": round(mean_final / (mean_tts / 1000), 3) if mean_tts else None,
        "tokens_to_solve": round(mean_tts) if mean_tts else None,
        "gen_tokens": round(_mean([r["metrics"].get("gen_tokens") for r in eff]) or 0) or None,
        "reasoning_tokens": round(rea) if rea is not None else None,
        "n_ctx_limited": n_ctx_limited,
    }


def _held_out(code_rs, release_date: str | None, training_cutoff: str | None) -> dict:
    """Contamination-adjusted code score for one run: mean score over code challenges PUBLISHED
    AFTER the model's release_date (the scores it provably couldn't have trained on), plus the
    secondary claimed-clean view vs training_cutoff. Same population as code_score, filtered to
    challenges newer than the boundary."""
    items = [{"published_at": r.get("published_at"), "score": {"final": _final(r)}} for r in code_rs]
    views = contamination.held_out_views(items, release_date, training_cutoff)
    off, clm = views["official"], views["claimed"]
    return {
        "held_out_score": off.score,
        "held_out": {
            "score": off.score,
            "claimed_score": clm.score if clm else None,
            "boundary": off.boundary,
            "n_clean": off.n_clean,
            "n_contaminated": off.n_contaminated,
            "n_unknown": off.n_unknown,
            "coverage": round(off.coverage, 3),
        },
    }


def _sol_per_s(rs) -> float | None:
    """Challenges solved per second over the run's total model time (sum of per-challenge latency)."""
    lat = _total_time(rs)
    return round(len(rs) / lat, 3) if lat else None


def _total_time(rs) -> float | None:
    """Total run time = sum of per-challenge model time (latency_s). None if no timing recorded."""
    lat = sum(r.get("latency_s") or 0 for r in rs if r.get("latency_s"))
    return round(lat, 1) if lat > 0 else None


def summarize_rows(rows: list[dict], release_date: str | None = None,
                   training_cutoff: str | None = None, *,
                   agent_isolating_only: bool = False) -> dict:
    """One run's result rows → the full leaderboard axis dict (the row shape GET /leaderboard
    serves, minus family/run info). Byte-identical to the API's historical `_summarize`.

    `agent_isolating_only` (the PUBLIC board sets it): agent_score counts only goal-state-env rows
    whose recorded provenance shows an isolating provider (docker/microvm/firecracker). A
    local-provider run executes on the submitter's host with no network conditions applied — fine
    for their own local board, but on the public board it must not be indistinguishable from a
    faithful environment. Rows with no provenance at all are excluded too (can't be told apart)."""
    # Commit-and-reveal: a sealed private row is a timestamped CLAIM, not evidence — it earns no
    # credit on any axis until revealed. Committed/revealed counts are surfaced so selective
    # reveal (the file-drawer) stays visible rather than hidden.
    n_committed = sum(1 for r in rows if r.get("private"))
    n_revealed = sum(1 for r in rows if r.get("private") and r.get("revealed"))
    rs = [r for r in rows if not r.get("private") or r.get("revealed")]
    # capability axes, kept separate: coding ability, safety/honesty, agentic (goal-state-env,
    # multi-machine), and planning (planner plans → fixed coder executes → tests). A planner/agent
    # isn't a "coder" and vice-versa. NOTE: these predicates are deliberately NON-exclusive
    # (verbatim from the API) — only `code` excludes goal-state-env; `axis_of` is the EXCLUSIVE
    # variant used by `peakstone check`'s split.
    agent_rs = [r for r in rs if (r.get("verification") or "") == "goal-state-env"]
    if agent_isolating_only:
        agent_rs = [r for r in agent_rs
                    if (r.get("env") or {}).get("provider") not in (None, "local")]
    agent = [_final(r) for r in agent_rs]
    planner = [_final(r) for r in rs if (r.get("category") or "") == "planner"]
    math_rs = [r for r in rs if (r.get("category") or "") == "math"]   # answer-match — its own axis
    longctx_rs = [r for r in rs if (r.get("category") or "") == "long-context"]
    code_rs = [r for r in rs if (r.get("category") or "") not in SAFETY
               and (r.get("category") or "") not in ("planner", "math", "long-context")
               and (r.get("verification") or "") != "goal-state-env"]
    code = [_final(r) for r in code_rs]
    safety = [_final(r) for r in rs if (r.get("category") or "") in SAFETY]
    by_cat = defaultdict(list)
    for r in rs:
        by_cat[r.get("category") or "other"].append(_final(r))
    return {
        "code_score": avg(code),
        **_held_out(code_rs, release_date, training_cutoff),
        **_ctx_efficiency(code_rs),               # context-efficiency: score_per_1k_tokens, n_ctx_limited, …
        "math_score": avg([_final(r) for r in math_rs]),
        "math_held_out": _held_out(math_rs, release_date, training_cutoff)["held_out"],
        "long_ctx_score": avg([_final(r) for r in longctx_rs]),   # comprehension over a long context
        "n_long_ctx": len(longctx_rs),
        **_calibration(rs),                       # metacognition: self_verify_accuracy + confidence_score
        **_self_repair(rs),                        # debugging: recovery_rate (headline stays first-try)
        **_truncation(rs),                         # budget-fit warning: truncation_rate (lower=better)

        "safety_score": avg(safety),
        "agent_score": avg(agent),
        "agent_held_out": _held_out(agent_rs, release_date, training_cutoff)["held_out"],
        "planner_score": avg(planner),
        "solved": sum(1 for x in code if x >= 0.999),
        "n_code": len(code),
        "n_math": len(math_rs),
        "n_agent": len(agent),
        "n_planner": len(planner),
        "n_total": len(rs),                              # coverage: challenges in the run
        "n_committed": n_committed,                      # sealed private claims (no credit until reveal)
        "n_revealed": n_revealed,                        # of those, opened + counting
        "sol_per_s": _sol_per_s(rs),                     # throughput: challenges per second of work
        "total_time_s": _total_time(rs),                 # wall: sum of per-challenge model time
        "by_category": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_cat.items())},
        "tok_per_s": avg([r.get("tok_per_s") for r in rs]),
        "metrics": _agg_metrics(rs),
    }

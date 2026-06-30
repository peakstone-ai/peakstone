"""Peakstone API — submission ingest + faceted leaderboards.

Run (dev, SQLite):   uvicorn api.main:app --reload
Run (Postgres):      PEAKSTONE_DATABASE_URL=postgresql+psycopg://... uvicorn api.main:app
"""
from __future__ import annotations

import lzma
import os
import re
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from . import identity, ingest, models, proposals
from .db import get_session, init_db
from ..engine import contamination
from ..engine.bundle import reasoning_mode

# Capability categories that are safety/honesty, not coding ability — scored separately so a strong
# coder isn't penalised (or flattered) in the headline code score (mirrors the report's split).
SAFETY = {"injection", "refusal", "hallucination", "security", "secure-code"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Peakstone API", version="0.1.0", lifespan=lifespan)


class _XzBody:
    """ASGI middleware: transparently decompress an xz/lzma request body (Content-Encoding: xz) so the
    route sees plain JSON. Bundles are large transcript-heavy JSON; the client compresses the upload
    (~6.5-8x) to cut bandwidth. Uncompressed requests (every other endpoint) pass straight through.

    Zip-bomb guarded — /submissions is public, so a tiny body must not expand to GBs: cap the on-wire
    size, decompress with a hard OUTPUT cap, and bound the lzma dictionary via memlimit. Real bundles
    are ~1.4 MB raw / ~0.2 MB xz, so the defaults leave generous headroom."""

    MAX_COMPRESSED = int(os.environ.get("PEAKSTONE_MAX_UPLOAD_MB", "8")) * 1024 * 1024
    MAX_DECOMPRESSED = int(os.environ.get("PEAKSTONE_MAX_BUNDLE_MB", "64")) * 1024 * 1024
    LZMA_MEMLIMIT = 128 * 1024 * 1024                    # bounds a malicious xz dictionary allocation

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not any(
                k == b"content-encoding" and v.strip().lower() == b"xz" for k, v in scope["headers"]):
            return await self.app(scope, receive, send)

        from starlette.responses import JSONResponse

        async def reject(detail, code):
            return await JSONResponse({"detail": detail}, status_code=code)(scope, receive, send)

        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if len(body) > self.MAX_COMPRESSED:          # cap the on-wire size (don't read unbounded)
                return await reject("compressed body too large", 413)
            if not msg.get("more_body"):
                break
        try:                                             # output-capped → a bomb is rejected, not materialized
            d = lzma.LZMADecompressor(memlimit=self.LZMA_MEMLIMIT)
            out = d.decompress(body, self.MAX_DECOMPRESSED + 1)
            if len(out) > self.MAX_DECOMPRESSED or not d.eof:
                return await reject("decompressed body too large", 413)
        except (lzma.LZMAError, EOFError, OSError):
            return await reject("invalid xz body", 400)
        # strip content-encoding, fix content-length, replay the decompressed body once
        headers = [(k, v) for k, v in scope["headers"] if k != b"content-encoding"]
        headers = [(k, str(len(out)).encode() if k == b"content-length" else v) for k, v in headers]
        scope = {**scope, "headers": headers}
        sent = False

        async def receive2():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": out, "more_body": False}

        return await self.app(scope, receive2, send)


app.add_middleware(_XzBody)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/submissions", status_code=201)
def post_submission(bundle: dict = Body(...), db: Session = Depends(get_session)):
    """Validate (schema + content-hash + signature) and store a result bundle. An xz-compressed body
    (Content-Encoding: xz) is transparently decompressed by the _XzBody middleware before this runs, so
    large transcript-heavy uploads cost ~6.5-8x less bandwidth."""
    try:
        sub = ingest.ingest_bundle(db, bundle)
    except ingest.IngestError as e:
        msg = str(e)
        raise HTTPException(status_code=409 if "already submitted" in msg else 400, detail=msg)
    return {"id": sub.id, "bundle_hash": sub.bundle_hash, "trust_tier": sub.trust_tier,
            "n_results": len(sub.results), "suite": f"{sub.suite_name}@{sub.suite_version}"}


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


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

# The default leaderboard lens is the contamination-filtered (held-out) score, scoped to the official
# suite so it's apples-to-apples. A model needs at least this much held-out evidence to be *ranked*
# rather than *provisional* (shown below, by all-corpus code score) — a model is never dropped from
# the default board for lacking a held-out score, only demoted. Thresholds are tunable as the corpus
# accrues dated challenges (the board self-heals: provisional models cross the bar over time).
HELD_OUT_MIN_CLEAN = 5
HELD_OUT_MIN_COVERAGE = 0.5
# "name@version" of the suite the default board scopes to. Unset (dev) -> the board spans all suites.
OFFICIAL_SUITE = os.environ.get("PEAKSTONE_OFFICIAL_SUITE")


# token-efficiency keys live in result.metrics but are summarized specially (honest, ctx-limited-aware)
# in _ctx_efficiency — keep them out of the generic leanness aggregate so each is reported once.
_TOKEN_KEYS = {"gen_tokens", "prompt_tokens", "tokens_to_solve", "ctx_limited", "reasoning_tokens"}


def _agg_metrics(rs) -> dict:
    """Average each efficiency metric over the results that recorded it (the run's leanness)."""
    buckets: dict[str, list] = defaultdict(list)
    for r in rs:
        for k, v in (r.metrics or {}).items():
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
        m = r.metrics or {}
        passed = 1.0 if r.final >= 0.999 else 0.0
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
    vals = [r.metrics["repair_recovered"] for r in rs
            if r.metrics and "repair_recovered" in r.metrics]
    return {
        "recovery_rate": round(sum(vals) / len(vals), 3) if vals else None,
        "n_repair": len(vals),
    }


def _truncation(rs) -> dict:
    """How often generation hit the token budget (max_tokens) instead of finishing on its own — i.e.
    the model was likely cut off mid-thought. Token-bound, so it's hardware-independent and fully
    reproducible; but a high rate is a WARNING that the budget is too tight to fairly measure this
    model's capability (its score is budget-limited, not ability-limited). Lower is better."""
    vals = [r.metrics["trunc_truncated"] for r in rs
            if r.metrics and "trunc_truncated" in r.metrics]
    return {
        "truncation_rate": round(sum(vals) / len(vals), 3) if vals else None,
        "n_generated": len(vals),
    }


def _ctx_efficiency(code_rs) -> dict:
    """Context-efficiency over code results. Excludes ctx-limited results (whose token counts are
    censored and scores depressed by window truncation, not capability) so the numbers are honest
    like-for-like. Tokens are model-native — compare within a family/tokenizer (quant/ctx), not across
    families. score_per_1k_tokens = mean code score per 1k tokens spent (capability per token)."""
    measured = [r for r in code_rs if (r.metrics or {}).get("tokens_to_solve")]
    n_ctx_limited = sum(1 for r in measured if (r.metrics or {}).get("ctx_limited"))
    eff = [r for r in measured if not (r.metrics or {}).get("ctx_limited")]
    if not eff:
        return {"score_per_1k_tokens": None, "tokens_to_solve": None, "gen_tokens": None,
                "reasoning_tokens": None, "n_ctx_limited": n_ctx_limited}

    def _mean(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return (sum(vals) / len(vals)) if vals else None

    mean_tts = _mean([r.metrics.get("tokens_to_solve") for r in eff])
    mean_final = sum(r.final for r in eff) / len(eff)
    rea = _mean([r.metrics.get("reasoning_tokens") for r in eff])    # None when the server never reported it
    return {
        "score_per_1k_tokens": round(mean_final / (mean_tts / 1000), 3) if mean_tts else None,
        "tokens_to_solve": round(mean_tts) if mean_tts else None,
        "gen_tokens": round(_mean([r.metrics.get("gen_tokens") for r in eff]) or 0) or None,
        "reasoning_tokens": round(rea) if rea is not None else None,
        "n_ctx_limited": n_ctx_limited,
    }


def _held_out(code_rs, fam: models.ModelFamily | None) -> dict:
    """Contamination-adjusted code score for one run: mean score over code challenges PUBLISHED
    AFTER the model's release_date (the scores it provably couldn't have trained on), plus the
    secondary claimed-clean view vs training_cutoff. Same population as code_score, filtered to
    challenges newer than the boundary."""
    rel = fam.release_date if fam else None
    cut = fam.training_cutoff if fam else None
    items = [{"published_at": r.published_at, "score": {"final": r.final}} for r in code_rs]
    views = contamination.held_out_views(items, rel, cut)
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


def _summarize(sub: models.Submission, fam: models.ModelFamily | None = None) -> dict:
    rs = sub.results
    # capability axes, kept separate: coding ability, safety/honesty, agentic (goal-state-env,
    # multi-machine), and planning (planner plans → fixed coder executes → tests). A planner/agent
    # isn't a "coder" and vice-versa.
    agent_rs = [r for r in rs if (r.verification or "") == "goal-state-env"]
    agent = [r.final for r in agent_rs]
    planner = [r.final for r in rs if (r.category or "") == "planner"]
    math_rs = [r for r in rs if (r.category or "") == "math"]   # answer-match — its own axis
    longctx_rs = [r for r in rs if (r.category or "") == "long-context"]  # long-window comprehension axis
    code_rs = [r for r in rs if (r.category or "") not in SAFETY
               and (r.category or "") not in ("planner", "math", "long-context")
               and (r.verification or "") != "goal-state-env"]
    code = [r.final for r in code_rs]
    safety = [r.final for r in rs if (r.category or "") in SAFETY]
    by_cat = defaultdict(list)
    for r in rs:
        by_cat[r.category or "other"].append(r.final)
    return {
        "code_score": _avg(code),
        **_held_out(code_rs, fam),
        **_ctx_efficiency(code_rs),               # context-efficiency: score_per_1k_tokens, n_ctx_limited, …
        "math_score": _avg([r.final for r in math_rs]),
        "math_held_out": _held_out(math_rs, fam)["held_out"],
        "long_ctx_score": _avg([r.final for r in longctx_rs]),   # comprehension over a long context
        "n_long_ctx": len(longctx_rs),
        **_calibration(rs),                       # metacognition: self_verify_accuracy + confidence_score
        **_self_repair(rs),                        # debugging: recovery_rate (headline stays first-try)
        **_truncation(rs),                         # budget-fit warning: truncation_rate (lower=better)

        "safety_score": _avg(safety),
        "agent_score": _avg(agent),
        "agent_held_out": _held_out(agent_rs, fam)["held_out"],   # SWE-bench-Live etc.: contamination-adjusted
        "planner_score": _avg(planner),
        "solved": sum(1 for x in code if x >= 0.999),
        "n_code": len(code),
        "n_math": len(math_rs),
        "n_agent": len(agent),
        "n_planner": len(planner),
        "n_total": len(rs),                              # coverage: challenges in the run
        "sol_per_s": _sol_per_s(rs),                     # throughput: challenges per second of work
        "total_time_s": _total_time(rs),                 # wall: sum of per-challenge model time
        "by_category": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_cat.items())},
        "tok_per_s": _avg([r.tok_per_s for r in rs]),
        "metrics": _agg_metrics(rs),
    }


def _sol_per_s(rs) -> float | None:
    """Challenges solved per second over the run's total model time (sum of per-challenge latency)."""
    lat = _total_time(rs)
    return round(len(rs) / lat, 3) if lat else None


def _total_time(rs) -> float | None:
    """Total run time = sum of per-challenge model time (latency_s). None if no timing recorded."""
    lat = sum(r.latency_s for r in rs if r.latency_s)
    return round(lat, 1) if lat > 0 else None


def _submitter_handle(db, sub: models.Submission) -> str | None:
    key = db.get(models.Key, sub.key_id)
    if key and key.user_id is not None:
        user = db.get(models.User, key.user_id)
        return user.handle if user else None
    return None


def _submission_reasoning(sub: models.Submission) -> str | None:
    """Reasoning run-condition for a submission — derived from its serve flags + observed CoT tokens
    (a thinking-on vs thinking-off run is a distinct, faceted run, like a quant)."""
    return reasoning_mode(sub.serve_flags, ((r.metrics or {}).get("reasoning_tokens") for r in sub.results))


def _submission_reasoning_budget(sub: models.Submission) -> int | None:
    """The thinking budget the run was SERVED at, from `--reasoning-budget N` in the serve flags:
    0 = off, -1 = full (unlimited), N = capped at N thinking tokens. None if the flag wasn't set.
    Finer than the on/off facet — lets the leaderboard plot accuracy vs thinking budget for a model."""
    m = re.search(r"--reasoning-budget\s+(-?\d+)", sub.serve_flags or "")
    return int(m.group(1)) if m else None


def _run_info(db, sub: models.Submission, art: models.ModelArtifact) -> dict:
    env = sub.env or {}
    return {"artifact": art.artifact, "hf_repo": art.hf_repo,
            "gpu": env.get("gpu"), "cpu": env.get("cpu"),                        # hardware it ran on
            "vram_gb": sub.vram_gb, "ram_gb": env.get("ram_gb"),                 # machine totals
            "vram_used_gb": env.get("vram_used_gb"), "ram_used_gb": env.get("ram_used_gb"),  # model footprint
            "context": sub.context, "engine": sub.engine, "trust_tier": sub.trust_tier,
            "reasoning": _submission_reasoning(sub),     # run condition: chain-of-thought on/off (or None)
            "reasoning_budget": _submission_reasoning_budget(sub),   # thinking budget served (0/-1/N)
            # negative data: a non-viable config (looped out of every category, passed nothing). Tied to
            # THIS run's (quant, ctx, reasoning), so it shows which configs aren't worth testing.
            "run_status": (sub.raw or {}).get("run_status"),
            "abandoned_categories": (sub.raw or {}).get("abandoned_categories"),
            "submitted_at": str(sub.submitted_at), "submitter": _submitter_handle(db, sub),
            "bundle_hash": sub.bundle_hash}


def _sort_value(row: dict, key: str):
    if key in row:
        return row.get(key)
    return (row.get("metrics") or {}).get(key)


@app.get("/leaderboard")
def leaderboard(db: Session = Depends(get_session), suite: str | None = None,
                version: str | None = None, max_vram_gb: float | None = None,
                quant: str | None = None, trust: str | None = None, reasoning: str | None = None,
                reasoning_budget: str | None = None, verdict: str | None = None,
                sort: str = "held_out_score", order: str | None = None, collapse: str = "family"):
    """Faceted: under the active filters, each family collapses to its best-qualifying run (§6a),
    then rows are ranked by `sort`.

    The DEFAULT lens is `held_out_score` (the contamination-filtered code score), scoped to the
    official suite — so the headline ranks models on challenges they provably couldn't have trained
    on. On that default board a model is never dropped for lacking a held-out score: models with
    enough held-out evidence are `ranked`; the rest are `provisional` (listed below, by all-corpus
    `code_score`). Specialised axis boards (`agent_score`/`planner_score`/efficiency) instead drop
    runs that have no value on that axis. `collapse='quant'` keeps the best run per (family, quant).
    Pass `suite=all` to span every suite instead of the official one."""
    if sort not in SORT_ORDER:
        sort = "held_out_score"
    if order not in ("asc", "desc"):
        order = SORT_ORDER[sort]
    # default the board to the official (suite, version) so the headline is apples-to-apples
    if suite is None and version is None and OFFICIAL_SUITE:
        name, _, ver = OFFICIAL_SUITE.partition("@")
        suite, version = name, (ver or None)
    q = select(models.Submission)
    if suite and suite != "all":
        q = q.where(models.Submission.suite_name == suite)
    if version:
        q = q.where(models.Submission.suite_version == version)
    if max_vram_gb is not None:
        q = q.where(models.Submission.vram_gb <= max_vram_gb)
    if trust:
        q = q.where(models.Submission.trust_tier == trust)

    default_heldout = sort == "held_out_score"
    # each family collapses to its best run for the chosen axis. On a specialised axis board a run
    # with no value there doesn't qualify (a safety-only run isn't a "coder"); on the default
    # held-out board we keep every family, falling back to code_score so provisional models still show.
    best: dict[str, dict] = {}
    for s in db.scalars(q).all():
        art = db.get(models.ModelArtifact, s.artifact_id)
        if quant and art.artifact != quant:
            continue
        if reasoning and (_submission_reasoning(s) or "none") != reasoning:
            continue                          # reasoning facet: thinking on/off is a distinct run
        if reasoning_budget is not None and str(_submission_reasoning_budget(s)) != reasoning_budget:
            continue                          # thinking-budget facet: a served --reasoning-budget value
        rs = (s.raw or {}).get("run_status")
        if verdict == "not_capable" and rs != "not_capable":
            continue                          # only the negative data: non-viable configs
        if verdict == "viable" and rs == "not_capable":
            continue                          # exclude non-viable configs from the board
        fam = db.get(models.ModelFamily, art.family_id)
        summ = _summarize(s, fam)
        row = {"family": fam.name, "release_date": fam.release_date,
               "observed_capabilities": sorted((fam.capabilities or {}).keys()), **summ,
               "run": _run_info(db, s, art)}
        val = _sort_value(row, sort)
        cmp_val = val if val is not None else (row.get("code_score") if default_heldout else None)
        if cmp_val is None:                   # no value on this axis (and not the held-out default)
            continue
        key = (f"{fam.name}\x00{art.artifact}\x00{_submission_reasoning(s) or 'none'}"
               f"\x00{_submission_reasoning_budget(s)}"
               if collapse == "quant" else fam.name)   # uncollapsed view splits thinking on/off AND budget
        cov = row.get("n_total") or 0
        cur = best.get(key)
        if cur is None:                       # keep the most-thorough qualifying run per group:
            better = True                     # prefer the most coverage, tie-break by the sort value
        elif cov != cur["_cov"]:
            better = cov > cur["_cov"]
        else:
            better = cmp_val > cur["_v"] if order == "desc" else cmp_val < cur["_v"]
        if better:
            best[key] = {**row, "_v": cmp_val, "_cov": cov}

    rows = list(best.values())
    if default_heldout:
        # two tiers: models with enough held-out evidence are ranked by held_out_score; the rest are
        # provisional, ranked below by all-corpus code_score (never dropped — the board self-heals).
        for r in rows:
            ho = r.get("held_out") or {}
            r["held_out_status"] = ("ranked" if r.get("held_out_score") is not None
                                    and ho.get("n_clean", 0) >= HELD_OUT_MIN_CLEAN
                                    and ho.get("coverage", 0) >= HELD_OUT_MIN_COVERAGE
                                    else "provisional")
        ranked = sorted((r for r in rows if r["held_out_status"] == "ranked"),
                        key=lambda r: r["held_out_score"], reverse=True)
        prov = sorted((r for r in rows if r["held_out_status"] == "provisional"),
                      key=lambda r: (r.get("code_score") or 0), reverse=True)
        rows = ranked + prov
    else:
        rows = sorted(rows, key=lambda r: r["_v"], reverse=(order == "desc"))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("_v", None)
        r.pop("_cov", None)
    return {"filters": {"suite": suite, "version": version, "max_vram_gb": max_vram_gb,
                        "quant": quant, "trust": trust, "reasoning": reasoning,
                        "reasoning_budget": reasoning_budget, "verdict": verdict, "sort": sort,
                        "order": order, "collapse": collapse},
            "thresholds": ({"held_out_min_clean": HELD_OUT_MIN_CLEAN,
                            "held_out_min_coverage": HELD_OUT_MIN_COVERAGE} if default_heldout else {}),
            "count": len(rows), "leaderboard": rows}


@app.get("/runs/{bundle_hash}")
def run_results(bundle_hash: str, db: Session = Depends(get_session)):
    """Per-challenge results for one run (submission) — the breakdown behind a leaderboard row. Lite:
    scores + the error type only, NOT the (potentially large) transcripts; fetch a single challenge's
    transcript on demand via /runs/{hash}/challenge/{id}."""
    sub = db.scalar(select(models.Submission).where(models.Submission.bundle_hash == bundle_hash))
    if not sub:
        raise HTTPException(404, "unknown run")
    results = [{"challenge": r.challenge_id, "category": r.category, "verification": r.verification,
                "final": r.final, "passed": r.passed, "total": r.total, "difficulty": r.difficulty,
                "error": (r.transcript or {}).get("error")}
               for r in sub.results]
    results.sort(key=lambda r: (r["category"] or "", r["challenge"]))
    return {"bundle_hash": bundle_hash, "n": len(results), "results": results}


@app.get("/runs/{bundle_hash}/challenge/{challenge_id}")
def run_challenge(bundle_hash: str, challenge_id: str, db: Session = Depends(get_session)):
    """One challenge's full result incl. transcript — fetched when the user opens the solution view."""
    sub = db.scalar(select(models.Submission).where(models.Submission.bundle_hash == bundle_hash))
    if not sub:
        raise HTTPException(404, "unknown run")
    r = next((x for x in sub.results if x.challenge_id == challenge_id), None)
    if not r:
        raise HTTPException(404, "unknown challenge in this run")
    return {"challenge": r.challenge_id, "final": r.final, "passed": r.passed, "total": r.total,
            "category": r.category, "transcript": r.transcript}


@app.get("/models/{family}")
def model_page(family: str, db: Session = Depends(get_session)):
    """Every run (no collapsing) for a model family — quants, contexts, hardware, trust tiers."""
    fam = db.scalar(select(models.ModelFamily).where(models.ModelFamily.name == family))
    if not fam:
        raise HTTPException(404, f"unknown family {family!r}")
    art_ids = [a.id for a in fam.artifacts]
    subs = db.scalars(select(models.Submission)
                      .where(models.Submission.artifact_id.in_(art_ids))
                      .order_by(models.Submission.submitted_at.desc())).all()
    runs = []
    for s in subs:
        art = db.get(models.ModelArtifact, s.artifact_id)
        runs.append({**_summarize(s, fam), "run": _run_info(db, s, art),
                     "suite": f"{s.suite_name}@{s.suite_version}"})
    return {"family": fam.name, "vendor": fam.vendor, "release_date": fam.release_date,
            "observed_capabilities": sorted((fam.capabilities or {}).keys()),
            "n_runs": len(runs), "runs": runs}


@app.get("/facets")
def facets(db: Session = Depends(get_session)):
    """Distinct filterable values for the leaderboard UI (quant pills, suite picker, trust filter)."""
    quants = db.scalars(select(distinct(models.ModelArtifact.artifact))
                        .order_by(models.ModelArtifact.artifact)).all()
    suites = db.execute(select(models.Submission.suite_name, models.Submission.suite_version)
                        .distinct().order_by(models.Submission.suite_name)).all()
    trusts = db.scalars(select(distinct(models.Submission.trust_tier))).all()
    # reasoning + budget are derived per-submission (serve flags + observed CoT), computed here
    subs = db.scalars(select(models.Submission)).all()
    reasonings = sorted({_submission_reasoning(s) for s in subs} - {None})
    budgets = sorted({_submission_reasoning_budget(s) for s in subs} - {None})
    _placeholder = {"(unknown)", "(unregistered)"}
    return {"quants": [q for q in quants if q and q not in _placeholder],
            "suites": [{"name": n, "version": v} for n, v in suites],
            "trust_tiers": sorted(trusts, key=lambda t: ingest.TRUST_ORDER.get(t, 0)),
            "reasoning": reasonings,                      # thinking on/off run-condition facet
            "reasoning_budgets": budgets,                 # served --reasoning-budget values (0/-1/N)
            "sort_axes": [{"key": k, "order": o} for k, o in SORT_ORDER.items()]}


@app.get("/challenges")
def challenges(db: Session = Depends(get_session)):
    """The challenge corpus with aggregate difficulty signal (pass-rate is the empirical tier)."""
    rows = db.execute(
        select(models.Result.challenge_id,
               func.count(models.Result.id).label("n"),
               func.avg(models.Result.final).label("avg"),
               func.sum(case((models.Result.final >= 0.999, 1), else_=0)).label("solved"))
        .group_by(models.Result.challenge_id)).all()
    stats = {r.challenge_id: r for r in rows}
    out = []
    for ch in db.scalars(select(models.Challenge).order_by(models.Challenge.id)).all():
        s = stats.get(ch.id)
        n = s.n if s else 0
        out.append({"id": ch.id, "title": ch.title, "language": ch.language,
                    "category": ch.category, "verification": ch.verification,
                    "seed_difficulty": ch.seed_difficulty, "status": ch.status,
                    "version": ch.version, "deprecated": ch.deprecated,
                    "n_runs": n, "avg_score": round(s.avg, 3) if s and s.avg is not None else None,
                    "pass_rate": round((s.solved or 0) / n, 3) if n else None})
    return {"count": len(out), "challenges": out}


@app.get("/challenges/{challenge_id}")
def challenge_detail(challenge_id: str, db: Session = Depends(get_session)):
    """Per-challenge mini-leaderboard: each family's best result on this one challenge."""
    ch = db.get(models.Challenge, challenge_id)
    if not ch:
        raise HTTPException(404, f"unknown challenge {challenge_id!r}")
    best: dict[str, dict] = {}
    for r in db.scalars(select(models.Result)
                        .where(models.Result.challenge_id == challenge_id)).all():
        sub = db.get(models.Submission, r.submission_id)
        art = db.get(models.ModelArtifact, sub.artifact_id)
        fam = db.get(models.ModelFamily, art.family_id)
        cur = best.get(fam.name)
        if cur is None or r.final > cur["score"]:
            best[fam.name] = {"family": fam.name, "score": round(r.final, 3),
                              "passed": r.passed, "total": r.total,
                              "run": _run_info(db, sub, art)}
    rows = sorted(best.values(), key=lambda x: -x["score"])
    return {"id": ch.id, "category": ch.category, "verification": ch.verification,
            "seed_difficulty": ch.seed_difficulty, "status": ch.status,
            "n_families": len(rows), "results": rows}


# --- account / identity binding ------------------------------------------------------------------

@app.post("/account/key-challenge")
def account_key_challenge(pubkey: str = Body(..., embed=True), db: Session = Depends(get_session)):
    """Issue a nonce the key must sign to prove ownership (step 1 of binding to an account)."""
    ch = identity.issue_key_challenge(db, pubkey)
    return {"nonce": ch.nonce, "expires_at": str(ch.expires_at)}


@app.get("/auth/{provider}/authorize-url")
def authorize_url(provider: str, redirect_uri: str = Query(...), state: str = Query(""),
                  db: Session = Depends(get_session)):
    """Build the provider's OAuth consent URL (the frontend redirects the browser here)."""
    try:
        prov = identity.get_provider(provider)
    except identity.BindError as e:
        raise HTTPException(503, str(e))
    return {"authorize_url": prov.authorize_url(state, redirect_uri)}


@app.post("/account/bind")
def account_bind(body: dict = Body(...), db: Session = Depends(get_session)):
    """Bind a key to an account: requires both a signed nonce (key proof) and an OAuth code."""
    try:
        fields = {k: body[k] for k in ("provider", "pubkey", "nonce", "signature", "code", "redirect_uri")}
    except KeyError as e:
        raise HTTPException(400, f"missing field {e}")
    if not all(isinstance(v, str) for v in fields.values()):
        raise HTTPException(400, "all bind fields must be strings")
    try:
        return identity.bind(db, **fields)
    except identity.BindError as e:
        msg = str(e)
        raise HTTPException(503 if "not configured" in msg else 400, msg)


@app.get("/account")
def account(pubkey: str = Query(...), db: Session = Depends(get_session)):
    """Who a key belongs to (the bound account + its providers), if any."""
    summary = identity.account_summary(db, pubkey)
    if summary is None:
        raise HTTPException(404, "key not bound to any account")
    return summary


# --- challenge moderation (open corpus → admin-canonized) ----------------------------------------

def _proposal_summary(p: models.ChallengeProposal) -> dict:
    return {"id": p.id, "slug": p.slug, "title": p.title, "language": p.language,
            "category": p.category, "difficulty": p.difficulty, "status": p.status,
            "reference_passes": (p.validation or {}).get("reference_passes"),
            "content_hash": p.content_hash, "created_at": str(p.created_at),
            "review_note": p.review_note}


@app.post("/proposals", status_code=201)
def propose_challenge(proposal: dict = Body(...), db: Session = Depends(get_session)):
    """Submit a signed challenge proposal (built by `python -m engine.propose`) to the queue."""
    try:
        p = proposals.propose(db, proposal)
    except proposals.ProposalError as e:
        msg = str(e)
        raise HTTPException(409 if "already submitted" in msg else 400, msg)
    return _proposal_summary(p)


@app.get("/proposals")
def list_proposals(status: str = "proposed", db: Session = Depends(get_session)):
    """The moderation queue (default: pending). status=all for every proposal."""
    q = select(models.ChallengeProposal).order_by(models.ChallengeProposal.created_at.desc())
    if status != "all":
        q = q.where(models.ChallengeProposal.status == status)
    rows = [_proposal_summary(p) for p in db.scalars(q).all()]
    return {"count": len(rows), "proposals": rows}


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: int, db: Session = Depends(get_session)):
    """Full proposal (spec + files) for review."""
    p = db.get(models.ChallengeProposal, proposal_id)
    if not p:
        raise HTTPException(404, f"unknown proposal {proposal_id}")
    return {**_proposal_summary(p), "spec": p.spec, "files": p.files,
            "scoring": p.scoring, "timeout": p.timeout, "validation": p.validation}


@app.post("/proposals/{proposal_id}/review")
def review_proposal(proposal_id: int, body: dict = Body(...), db: Session = Depends(get_session)):
    """Admin-signed approve/reject. Sign the message `<decision>:<content_hash>` with an admin key."""
    try:
        p = proposals.review(db, proposal_id, pubkey=body.get("pubkey", ""),
                             signature=body.get("signature", ""), decision=body.get("decision", ""),
                             note=body.get("note"))
    except proposals.AdminError as e:
        raise HTTPException(403, str(e))
    except proposals.ProposalError as e:
        msg = str(e)
        raise HTTPException(409 if "already" in msg else 400, msg)
    return _proposal_summary(p)


@app.post("/challenges/{challenge_id}/deprecate")
def deprecate_challenge(challenge_id: str, body: dict = Body(...), db: Session = Depends(get_session)):
    """Admin-signed deprecation. Sign the message `deprecate:<challenge_id>` with an admin key."""
    try:
        ch = proposals.deprecate(db, challenge_id, pubkey=body.get("pubkey", ""),
                                signature=body.get("signature", ""), note=body.get("note"))
    except proposals.AdminError as e:
        raise HTTPException(403, str(e))
    except proposals.ProposalError as e:
        raise HTTPException(400, str(e))
    return {"id": ch.id, "status": ch.status, "deprecated": ch.deprecated, "version": ch.version}

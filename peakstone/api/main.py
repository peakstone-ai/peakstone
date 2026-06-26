"""Peakstone API — submission ingest + faceted leaderboards.

Run (dev, SQLite):   uvicorn api.main:app --reload
Run (Postgres):      PEAKSTONE_DATABASE_URL=postgresql+psycopg://... uvicorn api.main:app
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from . import identity, ingest, models, proposals
from .db import get_session, init_db
from ..engine import contamination

# Capability categories that are safety/honesty, not coding ability — scored separately so a strong
# coder isn't penalised (or flattered) in the headline code score (mirrors the report's split).
SAFETY = {"injection", "refusal", "hallucination", "security", "secure-code"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Peakstone API", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/submissions", status_code=201)
def post_submission(bundle: dict = Body(...), db: Session = Depends(get_session)):
    """Validate (schema + content-hash + signature) and store a result bundle."""
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
              **METRIC_AXES}


def _agg_metrics(rs) -> dict:
    """Average each efficiency metric over the results that recorded it (the run's leanness)."""
    buckets: dict[str, list] = defaultdict(list)
    for r in rs:
        for k, v in (r.metrics or {}).items():
            if isinstance(v, (int, float)):
                buckets[k].append(v)
    return {k: round(sum(v) / len(v), 2) for k, v in buckets.items() if v}


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
    code_rs = [r for r in rs if (r.category or "") not in SAFETY
               and (r.category or "") not in ("planner", "math")
               and (r.verification or "") != "goal-state-env"]
    code = [r.final for r in code_rs]
    safety = [r.final for r in rs if (r.category or "") in SAFETY]
    by_cat = defaultdict(list)
    for r in rs:
        by_cat[r.category or "other"].append(r.final)
    return {
        "code_score": _avg(code),
        **_held_out(code_rs, fam),
        "math_score": _avg([r.final for r in math_rs]),
        "math_held_out": _held_out(math_rs, fam)["held_out"],
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
        "by_category": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_cat.items())},
        "tok_per_s": _avg([r.tok_per_s for r in rs]),
        "metrics": _agg_metrics(rs),
    }


def _sol_per_s(rs) -> float | None:
    """Challenges solved per second over the run's total model time (sum of per-challenge latency)."""
    lat = sum(r.latency_s for r in rs if r.latency_s)
    return round(len(rs) / lat, 3) if lat > 0 else None


def _submitter_handle(db, sub: models.Submission) -> str | None:
    key = db.get(models.Key, sub.key_id)
    if key and key.user_id is not None:
        user = db.get(models.User, key.user_id)
        return user.handle if user else None
    return None


def _run_info(db, sub: models.Submission, art: models.ModelArtifact) -> dict:
    env = sub.env or {}
    return {"artifact": art.artifact, "hf_repo": art.hf_repo,
            "gpu": env.get("gpu"), "cpu": env.get("cpu"),                        # hardware it ran on
            "vram_gb": sub.vram_gb, "ram_gb": env.get("ram_gb"),                 # machine totals
            "vram_used_gb": env.get("vram_used_gb"), "ram_used_gb": env.get("ram_used_gb"),  # model footprint
            "context": sub.context, "engine": sub.engine, "trust_tier": sub.trust_tier,
            "submitted_at": str(sub.submitted_at), "submitter": _submitter_handle(db, sub),
            "bundle_hash": sub.bundle_hash}


def _sort_value(row: dict, key: str):
    if key in row:
        return row.get(key)
    return (row.get("metrics") or {}).get(key)


@app.get("/leaderboard")
def leaderboard(db: Session = Depends(get_session), suite: str | None = None,
                version: str | None = None, max_vram_gb: float | None = None,
                quant: str | None = None, trust: str | None = None,
                sort: str = "code_score", order: str | None = None, collapse: str = "family"):
    """Faceted: under the active filters, each family collapses to its best-qualifying run (§6a),
    then rows are ranked by `sort` (code_score, or an efficiency axis like peak_rss_mb/loc).
    collapse='quant' instead keeps the best run per (family, quant) so different quants of a model
    appear as separate rows."""
    if sort not in SORT_ORDER:
        sort = "code_score"
    if order not in ("asc", "desc"):
        order = SORT_ORDER[sort]
    q = select(models.Submission)
    if suite:
        q = q.where(models.Submission.suite_name == suite)
    if version:
        q = q.where(models.Submission.suite_version == version)
    if max_vram_gb is not None:
        q = q.where(models.Submission.vram_gb <= max_vram_gb)
    if trust:
        q = q.where(models.Submission.trust_tier == trust)

    # each family collapses to its best run *for the chosen axis* — so sort=agent_score ranks each
    # family's best agentic run, sort=code_score its best coding run. Runs with no value on the axis
    # don't qualify for that board at all (a safety-only or agent-only run isn't a "coder").
    best: dict[str, dict] = {}
    for s in db.scalars(q).all():
        art = db.get(models.ModelArtifact, s.artifact_id)
        if quant and art.artifact != quant:
            continue
        fam = db.get(models.ModelFamily, art.family_id)
        summ = _summarize(s, fam)
        row = {"family": fam.name, "release_date": fam.release_date,
               "observed_capabilities": sorted((fam.capabilities or {}).keys()), **summ,
               "run": _run_info(db, s, art)}
        val = _sort_value(row, sort)
        if val is None:
            continue
        key = f"{fam.name}\x00{art.artifact}" if collapse == "quant" else fam.name
        cov = row.get("n_total") or 0
        cur = best.get(key)
        if cur is None:                       # keep the most-thorough qualifying run per group:
            better = True                     # prefer the most coverage, tie-break by the sort value
        elif cov != cur["_cov"]:
            better = cov > cur["_cov"]
        else:
            better = val > cur["_v"] if order == "desc" else val < cur["_v"]
        if better:
            best[key] = {**row, "_v": val, "_cov": cov}
    rows = sorted(best.values(), key=lambda r: r["_v"], reverse=(order == "desc"))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("_v", None)
        r.pop("_cov", None)
    return {"filters": {"suite": suite, "version": version, "max_vram_gb": max_vram_gb,
                        "quant": quant, "trust": trust, "sort": sort, "order": order, "collapse": collapse},
            "count": len(rows), "leaderboard": rows}


@app.get("/runs/{bundle_hash}")
def run_results(bundle_hash: str, db: Session = Depends(get_session)):
    """Per-challenge results for one run (submission) — the breakdown behind a leaderboard row."""
    sub = db.scalar(select(models.Submission).where(models.Submission.bundle_hash == bundle_hash))
    if not sub:
        raise HTTPException(404, "unknown run")
    results = [{"challenge": r.challenge_id, "category": r.category, "verification": r.verification,
                "final": r.final, "passed": r.passed, "total": r.total, "difficulty": r.difficulty,
                "transcript": r.transcript}
               for r in sub.results]
    results.sort(key=lambda r: (r["category"] or "", r["challenge"]))
    return {"bundle_hash": bundle_hash, "n": len(results), "results": results}


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
    _placeholder = {"(unknown)", "(unregistered)"}
    return {"quants": [q for q in quants if q and q not in _placeholder],
            "suites": [{"name": n, "version": v} for n, v in suites],
            "trust_tiers": sorted(trusts, key=lambda t: ingest.TRUST_ORDER.get(t, 0)),
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

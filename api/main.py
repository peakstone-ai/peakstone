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

from . import identity, ingest, models
from .db import get_session, init_db

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


def _summarize(sub: models.Submission) -> dict:
    rs = sub.results
    code = [r.final for r in rs if (r.category or "") not in SAFETY]
    safety = [r.final for r in rs if (r.category or "") in SAFETY]
    by_cat = defaultdict(list)
    for r in rs:
        by_cat[r.category or "other"].append(r.final)
    return {
        "code_score": _avg(code),
        "safety_score": _avg(safety),
        "solved": sum(1 for x in code if x >= 0.999),
        "n_code": len(code),
        "by_category": {k: round(sum(v) / len(v), 3) for k, v in sorted(by_cat.items())},
        "tok_per_s": _avg([r.tok_per_s for r in rs]),
    }


def _submitter_handle(db, sub: models.Submission) -> str | None:
    key = db.get(models.Key, sub.key_id)
    if key and key.user_id is not None:
        user = db.get(models.User, key.user_id)
        return user.handle if user else None
    return None


def _run_info(db, sub: models.Submission, art: models.ModelArtifact) -> dict:
    return {"artifact": art.artifact, "vram_gb": sub.vram_gb, "context": sub.context,
            "engine": sub.engine, "trust_tier": sub.trust_tier, "submitted_at": str(sub.submitted_at),
            "submitter": _submitter_handle(db, sub), "bundle_hash": sub.bundle_hash}


@app.get("/leaderboard")
def leaderboard(db: Session = Depends(get_session), suite: str | None = None,
                version: str | None = None, max_vram_gb: float | None = None,
                quant: str | None = None, trust: str | None = None):
    """Faceted: under the active filters, each family collapses to its best-qualifying run (§6a)."""
    q = select(models.Submission)
    if suite:
        q = q.where(models.Submission.suite_name == suite)
    if version:
        q = q.where(models.Submission.suite_version == version)
    if max_vram_gb is not None:
        q = q.where(models.Submission.vram_gb <= max_vram_gb)
    if trust:
        q = q.where(models.Submission.trust_tier == trust)

    best: dict[str, dict] = {}
    for s in db.scalars(q).all():
        art = db.get(models.ModelArtifact, s.artifact_id)
        if quant and art.artifact != quant:
            continue
        fam = db.get(models.ModelFamily, art.family_id)
        summ = _summarize(s)
        score = summ["code_score"] or -1.0
        cur = best.get(fam.name)
        if cur is None or score > cur["_score"]:
            best[fam.name] = {"family": fam.name, "release_date": fam.release_date,
                              "_score": score, **summ, "run": _run_info(db, s, art)}
    rows = sorted(best.values(), key=lambda r: -(r["code_score"] or -1))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("_score", None)
    return {"filters": {"suite": suite, "version": version, "max_vram_gb": max_vram_gb,
                        "quant": quant, "trust": trust}, "count": len(rows), "leaderboard": rows}


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
        runs.append({**_summarize(s), "run": _run_info(db, s, art),
                     "suite": f"{s.suite_name}@{s.suite_version}"})
    return {"family": fam.name, "vendor": fam.vendor, "release_date": fam.release_date,
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
            "trust_tiers": sorted(trusts, key=lambda t: ingest.TRUST_ORDER.get(t, 0))}


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
        out.append({"id": ch.id, "category": ch.category, "verification": ch.verification,
                    "seed_difficulty": ch.seed_difficulty, "status": ch.status,
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
        return identity.bind(
            db, provider=body["provider"], pubkey=body["pubkey"], nonce=body["nonce"],
            signature=body["signature"], code=body["code"], redirect_uri=body["redirect_uri"])
    except KeyError as e:
        raise HTTPException(400, f"missing field {e}")
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

"""Peakstone API — submission ingest + faceted leaderboards.

Run (dev, SQLite):   uvicorn api.main:app --reload
Run (Postgres):      PEAKSTONE_DATABASE_URL=postgresql+psycopg://... uvicorn api.main:app
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ingest, models
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


def _run_info(db, sub: models.Submission, art: models.ModelArtifact) -> dict:
    return {"artifact": art.artifact, "vram_gb": sub.vram_gb, "context": sub.context,
            "engine": sub.engine, "trust_tier": sub.trust_tier, "submitted_at": str(sub.submitted_at),
            "bundle_hash": sub.bundle_hash}


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
            best[fam.name] = {"family": fam.name, "_score": score, **summ,
                              "run": _run_info(db, s, art)}
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

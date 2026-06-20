"""Validate and store a submitted result bundle.

Trust chain at ingest: (1) JSON Schema valid, (2) re-derived bundle_hash matches the claimed one
(content-address), (3) ed25519 signature over that hash verifies. Only then is the run stored
(trust_tier='self-reported'; community/runner verification is computed later, P1.6).
"""
from __future__ import annotations

from sqlalchemy import select

from engine import bundle as eng_bundle  # the engine is the source of truth for hashing/validation
from engine import keys

from . import models


class IngestError(ValueError):
    """Bad/rejected bundle (maps to HTTP 400/409)."""


def _get_or_create(db, model, defaults=None, **filters):
    obj = db.scalar(select(model).filter_by(**filters))
    if obj:
        return obj
    obj = model(**filters, **(defaults or {}))
    db.add(obj)
    db.flush()
    return obj


def _get_artifact(db, family, m):
    return _get_or_create(
        db, models.ModelArtifact,
        defaults={"hf_revision": m.get("hf_revision"),
                  "params_total": m.get("params_total"), "params_active": m.get("params_active")},
        family_id=family.id, hf_repo=m.get("hf_repo", "(unknown)"),
        artifact=m.get("artifact", "(unknown)"), file_sha256=m.get("file_sha256"),
    )


def ingest_bundle(db, b: dict) -> models.Submission:
    # 1) schema
    try:
        eng_bundle._validate(b)
    except Exception as e:  # noqa: BLE001
        raise IngestError(f"schema invalid: {e}")

    # 2) content-address: re-derive bundle_hash and require a match
    claimed = b.get("bundle_hash")
    recomputed = eng_bundle._sha256_bytes(eng_bundle.canonical_bytes(eng_bundle._without_sig(b)))
    if not claimed or claimed != recomputed:
        raise IngestError("bundle_hash mismatch (content-address failed)")

    # 3) signature
    sub = b.get("submitter") or {}
    pub, sig = sub.get("pubkey"), sub.get("signature")
    if not (pub and sig):
        raise IngestError("missing submitter pubkey/signature")
    if not keys.verify(pub, sig, claimed.encode()):
        raise IngestError("signature verification failed")

    # 4) dedupe (content-addressed -> identical bundle can't be double-counted)
    if db.scalar(select(models.Submission).where(models.Submission.bundle_hash == claimed)):
        raise IngestError("bundle already submitted")

    # 5) upserts
    m, suite, env = b["model"], b["suite"], b["environment"]
    family = _get_or_create(db, models.ModelFamily, name=m["family"])
    artifact = _get_artifact(db, family, m)
    key = _get_or_create(db, models.Key, pubkey=pub)
    _get_or_create(db, models.Suite, defaults={"content_hash": suite.get("content_hash")},
                   name=suite["id"], version=suite["version"])

    submission = models.Submission(
        bundle_hash=claimed, key_id=key.id, artifact_id=artifact.id,
        suite_name=suite["id"], suite_version=suite["version"],
        engine=m.get("engine", {}), sampling=m.get("sampling", {}),
        serve_flags=m.get("serve_flags"), context=m.get("context"),
        env=env, vram_gb=env.get("vram_gb"), harness_version=b.get("harness", {}).get("version"),
        raw=b,
    )
    db.add(submission)
    db.flush()

    for r in b["results"]:
        sc = r.get("score", {})
        db.add(models.Result(
            submission_id=submission.id, challenge_id=r["challenge_id"],
            challenge_hash=r.get("challenge_hash"), category=r.get("category"),
            verification=r.get("verification"), difficulty=r.get("difficulty"),
            final=float(sc.get("final", 0.0)), passed=sc.get("passed"), total=sc.get("total"),
            tok_per_s=r.get("tok_per_s"), latency_s=r.get("latency_s"), metrics=r.get("metrics"),
        ))
        # lazily register the challenge in the corpus
        ch = db.get(models.Challenge, r["challenge_id"])
        if not ch:
            db.add(models.Challenge(
                id=r["challenge_id"], category=r.get("category"),
                verification=r.get("verification"), seed_difficulty=r.get("difficulty"),
                content_hash=r.get("challenge_hash")))

    db.commit()
    db.refresh(submission)
    return submission

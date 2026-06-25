"""Validate and store a submitted result bundle.

Trust chain at ingest: (1) JSON Schema valid, (2) re-derived bundle_hash matches the claimed one
(content-address), (3) ed25519 signature over that hash verifies. Only then is the run stored
(trust_tier='self-reported'; community/runner verification is computed later, P1.6).
"""
from __future__ import annotations

import hashlib
import json
import math
import os

from sqlalchemy import select

from peakstone.engine import bundle as eng_bundle  # the engine is the source of truth for hashing/validation
from peakstone.engine import keys

from . import models

# Trust tiers, weakest → strongest. A run is promoted to community-verified once enough *distinct
# identities* independently reproduce its deterministic result vector (PLAN §5). runner-verified is
# set out-of-band by a trusted re-runner and never downgraded here.
TRUST_ORDER = {"self-reported": 0, "community-verified": 1, "runner-verified": 2}
# Distinct identities required to promote to community-verified (a bound account counts once even
# across several of its keys; unbound keys each count once). Calibratable; 2 is the floor.
COMMUNITY_MIN_IDENTITIES = int(os.environ.get("PEAKSTONE_COMMUNITY_MIN_IDENTITIES", "2"))


class IngestError(ValueError):
    """Bad/rejected bundle (maps to HTTP 400/409)."""


def _repro_sig(results: list[dict]) -> str | None:
    """Fingerprint the deterministic result vector — the thing a reproduction must match.

    Only deterministic-tests results count (llm-judge/human aren't reproducible). Scores are
    rounded so floating-point noise doesn't split a genuine reproduction. None if nothing
    deterministic ran (such a run can never be community-verified)."""
    det = [(r["challenge_id"], round(float(r.get("score", {}).get("final", 0.0)), 4))
           for r in results if r.get("verification", "deterministic-tests") == "deterministic-tests"]
    if not det:
        return None
    payload = json.dumps(sorted(det), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _identity_of(db, sub: models.Submission) -> str:
    """The reproduction identity of a submission: its bound account if the key is linked, else the
    key itself. Two keys owned by the same account count as ONE reproducer (anti-self-verify)."""
    key = db.get(models.Key, sub.key_id)
    if key and key.user_id is not None:
        return f"user:{key.user_id}"
    return f"key:{sub.key_id}"


def _recompute_trust(db, sub: models.Submission) -> None:
    """After inserting `sub`, promote every self-reported run in its reproduction group to
    community-verified once ≥ COMMUNITY_MIN_IDENTITIES distinct identities agree."""
    if not sub.repro_sig:
        return
    group = db.scalars(select(models.Submission).where(
        models.Submission.artifact_id == sub.artifact_id,
        models.Submission.suite_name == sub.suite_name,
        models.Submission.suite_version == sub.suite_version,
        models.Submission.repro_sig == sub.repro_sig,
    )).all()
    # Sybil resistance: only ACCOUNT-BOUND identities count. Unbound keys are free to mint, so
    # counting them would let one actor self-promote with N throwaway keypairs. Community-verified
    # therefore requires ≥N distinct bound accounts (bind a GitHub account to participate).
    identities = {i for i in (_identity_of(db, s) for s in group) if i.startswith("user:")}
    if len(identities) < COMMUNITY_MIN_IDENTITIES:
        return
    for s in group:
        if TRUST_ORDER.get(s.trust_tier, 0) < TRUST_ORDER["community-verified"]:
            s.trust_tier = "community-verified"


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

    # 1b) reject non-finite scores: NaN/Infinity validate as JSON `number` but poison every aggregate
    # (NaN >= 0.999 is always False; sorting on NaN is undefined) and corrupt the DB.
    for r in b.get("results", []):
        for v in (r.get("score", {}) or {}).values():
            if isinstance(v, float) and not math.isfinite(v):
                raise IngestError("non-finite score value (NaN/Infinity)")

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
    family = _get_or_create(db, models.ModelFamily,
                            defaults={"release_date": m.get("release_date"),
                                      "training_cutoff": m.get("training_cutoff"),
                                      "vendor": m.get("vendor")},
                            name=m["family"])
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
        repro_sig=_repro_sig(b["results"]),
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
            published_at=r.get("published_at"), published_at_source=r.get("published_at_source"),
        ))
        # lazily register the challenge in the corpus
        ch = db.get(models.Challenge, r["challenge_id"])
        if not ch:
            db.add(models.Challenge(
                id=r["challenge_id"], category=r.get("category"),
                verification=r.get("verification"), seed_difficulty=r.get("difficulty"),
                content_hash=r.get("challenge_hash")))

    _recompute_trust(db, submission)
    db.commit()
    db.refresh(submission)
    return submission

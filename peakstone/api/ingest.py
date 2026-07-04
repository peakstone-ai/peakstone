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
# Operator/runner keys trusted to seed the official board. A bundle signed by one of these is ingested
# as runner-verified, so the operator's own seed runs qualify for the RANKED held-out tier — while an
# anonymous self-reported submission cannot. Without this gate a single free keypair + forged
# release_date/published_at ranks #1 on the headline board (review M2). Comma-separated b64 pubkeys.
TRUSTED_PUBKEYS = {k.strip() for k in os.environ.get("PEAKSTONE_TRUSTED_PUBKEYS", "").split(",") if k.strip()}


class IngestError(ValueError):
    """Bad/rejected bundle (maps to HTTP 400/409)."""


def _repro_sig(results: list[dict]) -> str | None:
    """Fingerprint the deterministic result vector — the thing a reproduction must match.

    Only deterministic-tests results count (llm-judge/human aren't reproducible). Scores are
    rounded so floating-point noise doesn't split a genuine reproduction. None if nothing
    deterministic ran (such a run can never be community-verified)."""
    det = [(r["challenge_id"], round(float(r.get("score", {}).get("final", 0.0)), 4))
           for r in results if r.get("verification", "deterministic-tests") == "deterministic-tests"
           and not r.get("private")]   # private sets differ per submitter — they'd fragment
                                       # reproduction groups and break community verification
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


def reconcile_trusted_keys(db) -> int:
    """Promote every stored run signed by a currently-trusted operator key to runner-verified.

    Trust tier is stamped at INGEST, so a key added to PEAKSTONE_TRUSTED_PUBKEYS *after* its runs were
    submitted would otherwise stay self-reported and never rank. Run at startup (idempotent) so the
    ranked board reflects the current trusted set — including operator runs seeded before the key was
    trusted. Returns the number promoted. Never downgrades (runner-verified is the top tier)."""
    if not TRUSTED_PUBKEYS:
        return 0
    key_ids = [k.id for k in db.scalars(
        select(models.Key).where(models.Key.pubkey.in_(TRUSTED_PUBKEYS))).all()]
    if not key_ids:
        return 0
    subs = db.scalars(select(models.Submission).where(
        models.Submission.key_id.in_(key_ids),
        models.Submission.trust_tier != "runner-verified")).all()
    for s in subs:
        s.trust_tier = "runner-verified"
    if subs:
        db.commit()
    return len(subs)


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

    # 1b) reject non-finite numbers anywhere in a result: NaN/Infinity validate as JSON `number` but
    # poison every aggregate (NaN >= 0.999 is always False; sorting on NaN is undefined) AND make the
    # response unserialisable (Starlette renders with allow_nan=False -> 500), so a single bundle with
    # e.g. metrics.peak_rss_mb=NaN is a persistent DoS on the public board. Scan score/metrics/latency/
    # tok_per_s — every numeric that reaches an aggregate or the API response.
    def _nonfinite(x) -> bool:
        if isinstance(x, bool):
            return False
        if isinstance(x, float):
            return not math.isfinite(x)
        if isinstance(x, dict):
            return any(_nonfinite(v) for v in x.values())
        if isinstance(x, (list, tuple)):
            return any(_nonfinite(v) for v in x)
        return False
    for r in b.get("results", []):
        for fld in ("score", "metrics", "latency_s", "tok_per_s"):
            if _nonfinite(r.get(fld)):
                raise IngestError(f"non-finite numeric in result.{fld} (NaN/Infinity)")

    # 1c) commit-and-reveal shape: `private` and `commitment` come together or not at all, and a
    # private row must not smuggle content (transcript) or a forgeable publication date.
    for r in b.get("results", []):
        if bool(r.get("private")) != bool(r.get("commitment")):
            raise IngestError("private rows need a commitment (and commitments imply private)")
        if r.get("private") and (r.get("transcript") or r.get("published_at")):
            raise IngestError("a private row must not carry transcript/published_at")

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
        # a bundle signed by a trusted operator key is runner-verified (qualifies to rank); everyone
        # else starts self-reported and is promoted only by independent reproduction.
        trust_tier=("runner-verified" if pub in TRUSTED_PUBKEYS else "self-reported"),
        raw=b,
    )
    db.add(submission)
    db.flush()

    for r in b["results"]:
        sc = r.get("score", {})
        private = bool(r.get("private"))
        row = models.Result(
            submission_id=submission.id, challenge_id=r["challenge_id"],
            challenge_hash=r.get("challenge_hash"), category=r.get("category"),
            verification=r.get("verification"), difficulty=r.get("difficulty"),
            final=float(sc.get("final", 0.0)), passed=sc.get("passed"), total=sc.get("total"),
            tok_per_s=r.get("tok_per_s"), latency_s=r.get("latency_s"), metrics=r.get("metrics"),
            transcript=r.get("transcript"),   # solution + execution output (raw_output/stdout/stderr/plan)
            published_at=r.get("published_at"), published_at_source=r.get("published_at_source"),
            private=private, commitment=r.get("commitment"),
        )
        # a commitment already revealed by someone else opens this row too (late committer)
        if private:
            rev = db.scalar(select(models.Reveal).where(models.Reveal.commitment == r["commitment"]))
            if rev:
                row.revealed = True
                row.challenge_id = rev.challenge_id
                row.published_at = rev.revealed_at.date().isoformat()
                row.published_at_source = "private-reveal"
        db.add(row)
        # lazily register the challenge in the corpus — but NEVER from a sealed private row: its
        # challenge_id is an author-chosen slug that must not create (or be confused with) a
        # public corpus entry until reveal.
        if not private or row.revealed:
            ch = db.get(models.Challenge, row.challenge_id)
            if not ch:
                db.add(models.Challenge(
                    id=row.challenge_id, category=r.get("category"),
                    verification=r.get("verification"), seed_difficulty=r.get("difficulty"),
                    content_hash=r.get("challenge_hash")))

    # observed capabilities (positives) from this run -> union into the family (so others can import
    # a classification without re-testing). Mirrors engine.capabilities.observe on bundle-shaped rows.
    from ..engine import capabilities as caps_mod
    obs = caps_mod.observe([{"category": r.get("category"), "verification": r.get("verification"),
                             "final_score": (r.get("score") or {}).get("final", 0)} for r in b["results"]])
    if obs:
        family.capabilities = {**(family.capabilities or {}), **{k: True for k in obs}}

    _recompute_trust(db, submission)
    db.commit()
    db.refresh(submission)
    return submission

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
from datetime import datetime, timezone

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
# Minimum account age (days) for an identity to count toward community-verified. Fresh OAuth
# accounts are cheap to mint in pairs; an age bar makes self-verification a slow, deliberate act
# instead of a five-minute one. 0 = off (dev default); production sets this (see infra/.env.example).
COMMUNITY_MIN_ACCOUNT_AGE_DAYS = float(os.environ.get("PEAKSTONE_COMMUNITY_MIN_ACCOUNT_AGE_DAYS", "0"))
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
    rounded so floating-point noise doesn't split a genuine reproduction. The challenge
    content_hash is part of the fingerprint: "reproductions" must agree on the exact challenge
    CONTENT scored, not just ids + scores (two runs of divergent challenge versions must never
    verify each other). None if nothing deterministic ran (such a run can never be
    community-verified)."""
    det = [(r["challenge_id"], r.get("challenge_hash") or "",
            round(float(r.get("score", {}).get("final", 0.0)), 4))
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


def _seasoned(db, identity: str) -> bool:
    """Age bar (provenance): an identity counts toward community-verified only once its account is
    COMMUNITY_MIN_ACCOUNT_AGE_DAYS old. OAuth accounts are cheap to mint in pairs; age makes
    self-verification slow and deliberate instead of a five-minute act."""
    if COMMUNITY_MIN_ACCOUNT_AGE_DAYS <= 0:
        return True
    user = db.get(models.User, int(identity.removeprefix("user:")))
    if not user or user.created_at is None:
        return False
    created = user.created_at
    if created.tzinfo is None:               # SQLite drops tzinfo; stored values are UTC
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).days >= COMMUNITY_MIN_ACCOUNT_AGE_DAYS


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
    # therefore requires ≥N distinct bound accounts (bind a GitHub account to participate) that
    # each clear the account-age bar.
    identities = {i for i in (_identity_of(db, s) for s in group)
                  if i.startswith("user:") and _seasoned(db, i)}
    if len(identities) < COMMUNITY_MIN_IDENTITIES:
        return
    for s in group:
        if TRUST_ORDER.get(s.trust_tier, 0) < TRUST_ORDER["community-verified"]:
            s.trust_tier = "community-verified"


def recompute_repro_sigs(db) -> int:
    """Re-derive every stored submission's repro_sig from its raw bundle (idempotent; run at
    startup). Needed whenever the sig formula changes — e.g. challenge_hash joining the
    fingerprint — so old rows regroup correctly instead of new submissions never matching them.
    Never downgrades trust already granted; re-runs promotion for regrouped rows."""
    changed = []
    for s in db.scalars(select(models.Submission)).all():
        new = _repro_sig((s.raw or {}).get("results", []))
        if new != s.repro_sig:
            s.repro_sig = new
            changed.append(s)
    if changed:
        db.flush()
        for s in changed:
            _recompute_trust(db, s)
        db.commit()
    return len(changed)


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


def _reconcile_family(family: models.ModelFamily, m: dict, tier: str) -> None:
    """Family metadata (release_date — the contamination boundary — training_cutoff, vendor) is
    reconciled by trust, not first-writer-wins: a higher-trust submission overwrites what a
    lower-trust one set (name-squatting a family with a bogus release_date must not stick), an
    equal-trust one only fills gaps, a lower-trust one never touches it."""
    incoming = {k: m.get(k) for k in ("release_date", "training_cutoff", "vendor")}
    have, new = TRUST_ORDER.get(family.metadata_trust or "self-reported", 0), TRUST_ORDER.get(tier, 0)
    if new > have:
        for k, v in incoming.items():
            if v is not None:
                setattr(family, k, str(v) if k != "vendor" else v)
        family.metadata_trust = tier
    elif new == have:
        for k, v in incoming.items():
            if v is not None and getattr(family, k) is None:
                setattr(family, k, str(v) if k != "vendor" else v)


def _notarize_published_at(db, row: models.Result) -> None:
    """Server-side truth for `published_at` (the contamination clock): record when this exact
    challenge content (content_hash) was FIRST seen by the platform, and clamp any later claim
    down to it — the content demonstrably existed at first-seen, so a later date is refuted.
    Earlier claims are unfalsifiable but conservative for held-out scoring (they count the
    challenge as held-out for FEWER models), so they're kept."""
    h = row.challenge_hash
    if not h or h.startswith("("):        # no hash / "(private)" sentinel — nothing to notarize
        return
    sighting = _get_or_create(db, models.ChallengeSighting, content_hash=h)
    first_seen = sighting.first_seen_at
    if first_seen.tzinfo is None:          # SQLite drops tzinfo; stored values are UTC
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    first_seen_date = first_seen.date().isoformat()
    if row.published_at is None or row.published_at > first_seen_date:
        row.published_at = first_seen_date
        row.published_at_source = "platform-first-seen"


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
    # a bundle signed by a trusted operator key is runner-verified (qualifies to rank); everyone
    # else starts self-reported and is promoted only by independent reproduction.
    trust_tier = "runner-verified" if pub in TRUSTED_PUBKEYS else "self-reported"
    family = _get_or_create(db, models.ModelFamily,
                            defaults={"release_date": m.get("release_date"),
                                      "training_cutoff": m.get("training_cutoff"),
                                      "vendor": m.get("vendor"),
                                      "metadata_trust": trust_tier},
                            name=m["family"])
    _reconcile_family(family, m, trust_tier)
    artifact = _get_artifact(db, family, m)
    key = _get_or_create(db, models.Key, pubkey=pub)
    # Comparability check: the suite's content_hash is fixed by its first-seen bundle; a later
    # bundle claiming the same (suite, version) over a DIFFERENT challenge set is flagged, not
    # trusted-by-name. None = no basis (this bundle IS the first sighting, or a hash is missing).
    # (Flag rather than reject while pre-fix bundles — hashed over executed rows instead of the
    # selected set — are still on the board; the ranked tier can exclude False.)
    suite_row = db.scalar(select(models.Suite).filter_by(name=suite["id"], version=suite["version"]))
    suite_hash_match = None
    if suite_row is None:
        suite_row = _get_or_create(db, models.Suite,
                                   defaults={"content_hash": suite.get("content_hash")},
                                   name=suite["id"], version=suite["version"])
    elif suite_row.content_hash and suite.get("content_hash"):
        suite_hash_match = suite.get("content_hash") == suite_row.content_hash

    submission = models.Submission(
        bundle_hash=claimed, key_id=key.id, artifact_id=artifact.id,
        suite_name=suite["id"], suite_version=suite["version"],
        engine=m.get("engine", {}), sampling=m.get("sampling", {}),
        serve_flags=m.get("serve_flags"), context=m.get("context"),
        env=env, vram_gb=env.get("vram_gb"), harness_version=b.get("harness", {}).get("version"),
        repro_sig=_repro_sig(b["results"]),
        suite_hash_match=suite_hash_match,
        trust_tier=trust_tier,
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
        if not private:
            _notarize_published_at(db, row)   # server first-seen clamps a too-late claimed date
        db.add(row)
        # lazily register the challenge in the corpus — but NEVER from a sealed private row: its
        # challenge_id is an author-chosen slug that must not create (or be confused with) a
        # public corpus entry until reveal. Registration from an untrusted submission is
        # 'observed', not 'published': submitter-declared ids/categories/difficulties must not
        # mint canonical corpus entries (those come from the corpus/proposal flow or trusted runs).
        if not private or row.revealed:
            ch = db.get(models.Challenge, row.challenge_id)
            if not ch:
                db.add(models.Challenge(
                    id=row.challenge_id, category=r.get("category"),
                    verification=r.get("verification"), seed_difficulty=r.get("difficulty"),
                    content_hash=r.get("challenge_hash"),
                    status=("published" if trust_tier == "runner-verified" else "observed")))

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

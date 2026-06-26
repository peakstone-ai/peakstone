"""ORM models — the Peakstone data model (PLAN.md §6).

Runs are NEVER collapsed: a `submission` is one fully-specified config (artifact + quant + serve
flags + env) scored on a suite. Leaderboards are faceted queries over submissions/results.
Identity: the `key` (ed25519 pubkey) is the root; `users`/`identity_links` bind accounts to it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# JSON on SQLite, JSONB on Postgres
JSONv = JSON().with_variant(JSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ModelFamily(Base):
    __tablename__ = "model_families"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    vendor: Mapped[str | None] = mapped_column(String)
    release_date: Mapped[str | None] = mapped_column(String)  # ISO date; the evolution-chart x-axis
    # Claimed knowledge cutoff (self-reported). Backs only the secondary "claimed-clean" held-out
    # view; the official held-out metric uses release_date (unforgeable). See engine/contamination.py.
    training_cutoff: Mapped[str | None] = mapped_column(String)
    modality: Mapped[str] = mapped_column(String, default="text")
    # Capabilities OBSERVED across this family's submitted runs (positives only: e.g. it engaged tools
    # or resolved an agentic task). Lets others import a classification without re-testing.
    capabilities: Mapped[dict | None] = mapped_column(JSONv)
    artifacts: Mapped[list[ModelArtifact]] = relationship(back_populates="family")


class ModelArtifact(Base):
    """A specific quant/build of a family (the thing a run actually loads)."""
    __tablename__ = "model_artifacts"
    # family-scoped: the ingest lookup keys on family too, and two distinct families can both carry a
    # placeholder/unknown artifact identity (no sha) without colliding.
    __table_args__ = (UniqueConstraint("family_id", "hf_repo", "artifact", "file_sha256",
                                       name="uq_artifact"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("model_families.id"), index=True)
    artifact: Mapped[str] = mapped_column(String)          # e.g. UD-Q4_K_XL
    hf_repo: Mapped[str] = mapped_column(String)
    hf_revision: Mapped[str | None] = mapped_column(String)
    file_sha256: Mapped[str | None] = mapped_column(String, index=True)
    params_total: Mapped[str | None] = mapped_column(String)
    params_active: Mapped[str | None] = mapped_column(String)
    family: Mapped[ModelFamily] = relationship(back_populates="artifacts")


class Key(Base):
    """An ed25519 public key — the root submitter identity (may be pseudonymous, no user)."""
    __tablename__ = "keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    pubkey: Mapped[str] = mapped_column(String, unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    """Optional account; bound to one or more keys + provider identities (see IdentityLink)."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    handle: Mapped[str | None] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class IdentityLink(Base):
    """Pluggable auth binding: provider 'attests' an account owns a user (GitHub first, others later).
    Keyed by internal user_id — NEVER a provider id — so providers are additive, no lock-in."""
    __tablename__ = "identity_links"
    __table_args__ = (UniqueConstraint("provider", "provider_account_id", name="uq_identity"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String)          # github | gitlab | google | siwe | ...
    provider_account_id: Mapped[str] = mapped_column(String)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KeyChallenge(Base):
    """A short-lived nonce a key must sign to prove ownership before binding to an account.
    Single-use: consumed (deleted) when redeemed. (Account binding flow — see api/identity.py.)"""
    __tablename__ = "key_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    pubkey: Mapped[str] = mapped_column(String, index=True)
    nonce: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Challenge(Base):
    """Canonical corpus entry. Rows arrive two ways: lazily upserted from result submissions, or
    materialized when an admin approves a ChallengeProposal (then title/language/author are set)."""
    __tablename__ = "challenges"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # challenge slug, e.g. py-12-txn-kvstore
    title: Mapped[str | None] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String, index=True)
    verification: Mapped[str | None] = mapped_column(String)
    seed_difficulty: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deprecated: Mapped[bool] = mapped_column(default=False, index=True)
    author_key_id: Mapped[int | None] = mapped_column(ForeignKey("keys.id"))
    status: Mapped[str] = mapped_column(String, default="published", index=True)


class ChallengeProposal(Base):
    """An open-corpus submission awaiting admin review (the moderation queue). Content-addressed +
    author-signed; validation (reference passes its tests) is the author's self-reported claim, which
    a reviewer re-runs locally before approving — the API never executes the untrusted code."""
    __tablename__ = "challenge_proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    slug: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str | None] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    difficulty: Mapped[int | None] = mapped_column(Integer)
    scoring: Mapped[str | None] = mapped_column(String)
    timeout: Mapped[int | None] = mapped_column(Integer)
    spec: Mapped[str] = mapped_column(String)
    files: Mapped[dict] = mapped_column(JSONv)            # {relpath: content}: meta.toml + tests + reference
    validation: Mapped[dict] = mapped_column(JSONv)       # author's local reference run (self-reported)
    author_key_id: Mapped[int] = mapped_column(ForeignKey("keys.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="proposed", index=True)  # proposed|approved|rejected
    review_note: Mapped[str | None] = mapped_column(String)
    reviewed_by_key_id: Mapped[int | None] = mapped_column(ForeignKey("keys.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Suite(Base):
    __tablename__ = "suites"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_suite"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str | None] = mapped_column(String)
    official: Mapped[bool] = mapped_column(default=False)


class Submission(Base):
    """One run = one fully-specified config scored on a suite (never collapsed with other quants/cfgs)."""
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("keys.id"), index=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("model_artifacts.id"), index=True)
    suite_name: Mapped[str] = mapped_column(String, index=True)
    suite_version: Mapped[str] = mapped_column(String, index=True)
    engine: Mapped[dict] = mapped_column(JSONv)            # {name, version}
    sampling: Mapped[dict] = mapped_column(JSONv)
    serve_flags: Mapped[str | None] = mapped_column(String)
    context: Mapped[int | None] = mapped_column(Integer)
    env: Mapped[dict] = mapped_column(JSONv)               # gpu/driver/cpu/ram/vram/offload — faceting
    vram_gb: Mapped[float | None] = mapped_column(Float, index=True)  # denormalized for the VRAM filter
    harness_version: Mapped[str | None] = mapped_column(String)
    # Fingerprint of the deterministic result vector (sorted challenge->score). Two submissions of
    # the same artifact+suite with the same repro_sig are reproductions of each other → the basis
    # of the community-verified trust tier (see ingest._recompute_trust).
    repro_sig: Mapped[str | None] = mapped_column(String, index=True)
    trust_tier: Mapped[str] = mapped_column(String, default="self-reported", index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    raw: Mapped[dict] = mapped_column(JSONv)               # full bundle, for audit / re-verification
    results: Mapped[list[Result]] = relationship(back_populates="submission", cascade="all, delete-orphan")


class Result(Base):
    __tablename__ = "results"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    challenge_id: Mapped[str] = mapped_column(String, index=True)
    challenge_hash: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String, index=True)
    verification: Mapped[str | None] = mapped_column(String)
    difficulty: Mapped[int | None] = mapped_column(Integer)
    final: Mapped[float] = mapped_column(Float)
    passed: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    tok_per_s: Mapped[float | None] = mapped_column(Float)
    latency_s: Mapped[float | None] = mapped_column(Float)
    response: Mapped[str | None] = mapped_column(String)   # the model's output (proposed solution)
    metrics: Mapped[dict | None] = mapped_column(JSONv)    # P2: size/perf/memory efficiency axes
    # When this challenge's content first became public + where that date came from. Compared
    # against the model's release_date to decide contamination (engine/contamination.py).
    published_at: Mapped[str | None] = mapped_column(String)
    published_at_source: Mapped[str | None] = mapped_column(String)
    submission: Mapped[Submission] = relationship(back_populates="results")

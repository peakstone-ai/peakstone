"""Challenge moderation — propose → review → publish/deprecate (PLAN.md §9 P2a).

Open corpus: anyone signs + submits a challenge proposal (engine/propose.py builds it). It lands in
a queue; an admin (ed25519 allowlist) approves or rejects with a signed action. Approval materializes
a canonical Challenge (published, versioned, attributed). The API never runs the untrusted test /
reference code — `validation` is the author's self-reported local run, which a reviewer re-runs.
"""
from __future__ import annotations

from sqlalchemy import select

from engine.bundle import _sha256_bytes, canonical_bytes
from engine import keys as eng_keys

from . import identity, models
from .models import _utcnow

_SUPPORTED_LANGS = {"python", "javascript", "typescript", "go", "rust"}


class ProposalError(ValueError):
    """Bad/rejected proposal (maps to HTTP 400/409)."""


class AdminError(PermissionError):
    """Action not authorized by an admin key (maps to HTTP 403)."""


def _content_hash(p: dict) -> str:
    core = {k: v for k, v in p.items() if k not in ("validation", "submitter", "content_hash")}
    return _sha256_bytes(canonical_bytes(core))


def _get_or_create_key(db, pubkey: str) -> models.Key:
    key = db.scalar(select(models.Key).where(models.Key.pubkey == pubkey))
    if not key:
        key = models.Key(pubkey=pubkey)
        db.add(key)
        db.flush()
    return key


def propose(db, p: dict) -> models.ChallengeProposal:
    # 1) structure
    for k in ("slug", "language", "spec", "files", "content_hash", "submitter"):
        if not p.get(k):
            raise ProposalError(f"missing required field {k!r}")
    if p["language"] not in _SUPPORTED_LANGS:
        raise ProposalError(f"unsupported language {p['language']!r}")
    files = p["files"]
    if not isinstance(files, dict):
        raise ProposalError("files must be an object of {path: content}")
    if not any(k.startswith("tests/") for k in files):
        raise ProposalError("proposal has no tests/ files")
    if not any(k.startswith("reference/") for k in files):
        raise ProposalError("proposal has no reference/ files")

    # 2) content-address + 3) signature (same trust chain as result bundles)
    if _content_hash(p) != p["content_hash"]:
        raise ProposalError("content_hash mismatch")
    pub, sig = p["submitter"].get("pubkey"), p["submitter"].get("signature")
    if not (pub and sig):
        raise ProposalError("missing submitter pubkey/signature")
    if not eng_keys.verify(pub, sig, p["content_hash"].encode()):
        raise ProposalError("signature verification failed")

    # 4) dedupe
    if db.scalar(select(models.ChallengeProposal)
                 .where(models.ChallengeProposal.content_hash == p["content_hash"])):
        raise ProposalError("proposal already submitted")

    # 5) store
    author = _get_or_create_key(db, pub)
    prop = models.ChallengeProposal(
        content_hash=p["content_hash"], slug=p["slug"], title=p.get("title"),
        language=p["language"], category=p.get("category"), difficulty=p.get("difficulty"),
        scoring=p.get("scoring", "tests"), timeout=p.get("timeout"), spec=p["spec"], files=files,
        validation=p.get("validation") or {}, author_key_id=author.id, status="proposed",
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def review(db, proposal_id: int, *, pubkey: str, signature: str, decision: str,
           note: str | None = None) -> models.ChallengeProposal:
    if decision not in ("approve", "reject"):
        raise ProposalError("decision must be 'approve' or 'reject'")
    prop = db.get(models.ChallengeProposal, proposal_id)
    if not prop:
        raise ProposalError(f"unknown proposal {proposal_id}")
    # admin signs "<decision>:<content_hash>" so the signature can't be replayed for another action
    if not identity.verify_admin_action(pubkey, signature, f"{decision}:{prop.content_hash}"):
        raise AdminError("not authorized: action must be signed by an admin key")
    if prop.status != "proposed":
        raise ProposalError(f"proposal already {prop.status}")

    reviewer = _get_or_create_key(db, pubkey)
    prop.reviewed_by_key_id = reviewer.id
    prop.reviewed_at = _utcnow()
    prop.review_note = note
    prop.status = "approved" if decision == "approve" else "rejected"

    if decision == "approve":
        ch = db.get(models.Challenge, prop.slug)
        if ch is None:
            ch = models.Challenge(id=prop.slug)
            db.add(ch)
        else:
            ch.version = (ch.version or 1) + 1  # re-approval of a slug bumps the version
        ch.title = prop.title
        ch.language = prop.language
        ch.category = prop.category
        ch.seed_difficulty = prop.difficulty
        ch.content_hash = prop.content_hash
        ch.author_key_id = prop.author_key_id
        ch.deprecated = False
        ch.status = "published"
    db.commit()
    db.refresh(prop)
    return prop


def deprecate(db, challenge_id: str, *, pubkey: str, signature: str,
              note: str | None = None) -> models.Challenge:
    ch = db.get(models.Challenge, challenge_id)
    if not ch:
        raise ProposalError(f"unknown challenge {challenge_id!r}")
    if not identity.verify_admin_action(pubkey, signature, f"deprecate:{challenge_id}"):
        raise AdminError("not authorized: action must be signed by an admin key")
    ch.deprecated = True
    ch.status = "deprecated"
    db.commit()
    db.refresh(ch)
    return ch

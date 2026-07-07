"""Reproduce a published run (PLAN §12 D / vision §7): the deterministic result vector, the
client-side bundle trust chain, the reproduction plan, and the MATCH/COMPATIBLE/MISMATCH verdict.

The core claim of the platform is "verified, not trusted" — this module is the client half of
that: `peakstone reproduce <hash>` re-runs a bundle's DETERMINISTIC result vector on your own
hardware and compares. The vector definition here is the ONE declaration; the server's
community-verification fingerprint (api.ingest) delegates to it, so "your run matches" and "the
server promotes" can never drift apart.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import bundle as eng_bundle
from . import keys


# --------------------------------------------------------------------------- #
# the deterministic result vector — what a reproduction must match
# --------------------------------------------------------------------------- #
def det_vector(results: list[dict]) -> list[tuple[str, str, float]]:
    """The deterministic result vector of a bundle's results: (challenge_id, challenge_hash,
    rounded final) for every deterministic-tests, non-private row, sorted.

    Only deterministic-tests results count (llm-judge/human aren't reproducible). Scores are
    rounded so floating-point noise doesn't split a genuine reproduction. The challenge
    content_hash is part of the vector: "reproductions" must agree on the exact challenge CONTENT
    scored, not just ids + scores. Private (commit-and-reveal) rows are excluded — they differ per
    submitter and would fragment reproduction groups."""
    return sorted((r["challenge_id"], r.get("challenge_hash") or "",
                   round(float(r.get("score", {}).get("final", 0.0)), 4))
                  for r in results
                  if r.get("verification", "deterministic-tests") == "deterministic-tests"
                  and not r.get("private"))


def repro_sig(results: list[dict]) -> str | None:
    """Fingerprint of the deterministic result vector — equality means MATCH, and it is exactly
    what the server groups reproductions by. None if nothing deterministic ran (such a run can
    never be verified)."""
    det = det_vector(results)
    if not det:
        return None
    payload = json.dumps(det, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# client-side trust chain (mirrors ingest steps 1–3)
# --------------------------------------------------------------------------- #
def verify_bundle(b: dict) -> list[str]:
    """Verify a fetched bundle the same way ingest does before trusting it: schema-valid,
    content-addressed (bundle_hash re-derives), signature verifies. Returns the list of problems
    (empty = trustworthy). Run this on anything fetched over the network BEFORE reproducing it —
    a tampered bundle must fail here, not silently define your run."""
    problems: list[str] = []
    try:
        eng_bundle._validate(b)
    except Exception as e:  # noqa: BLE001
        problems.append(f"schema invalid: {e}")
    claimed = b.get("bundle_hash")
    recomputed = eng_bundle._sha256_bytes(eng_bundle.canonical_bytes(eng_bundle._without_sig(b)))
    if not claimed or claimed != recomputed:
        problems.append("bundle_hash mismatch (content-address failed)")
    sub = b.get("submitter") or {}
    pub, sig = sub.get("pubkey"), sub.get("signature")
    if not (pub and sig):
        problems.append("missing submitter pubkey/signature")
    elif claimed and not keys.verify(pub, sig, claimed.encode()):
        problems.append("signature verification failed")
    return problems


# --------------------------------------------------------------------------- #
# the plan: what to run, against which pinned content
# --------------------------------------------------------------------------- #
@dataclass
class ReproPlan:
    """Everything a client needs to faithfully re-run a bundle's deterministic vector."""
    ids: list[str]                    # the det-vector challenge ids — run exactly these, judge OFF
    suite_id: str
    suite_version: str
    family: str
    artifact: str                     # quant label — same-quant only, refuse otherwise
    hf_repo: str
    file_sha256: str                  # the exact weights; a different file is a different artifact
    max_tokens: int | None            # the run's generation budget (run identity)
    context: int | None               # served context window
    reasoning_budget: int | None      # served thinking budget (0=off, -1=full, N=cap), None=unset
    hash_mismatches: list[str] = field(default_factory=list)  # local corpus content differs
    missing: list[str] = field(default_factory=list)          # not in the local corpus at all

    @property
    def ready(self) -> bool:
        return bool(self.ids) and not self.hash_mismatches and not self.missing


def plan(b: dict, challenges_dir: Path) -> ReproPlan:
    """Build the reproduction plan for a verified bundle: the deterministic-vector ids (judge-graded
    and env rows are excluded — they aren't part of the verification vector), pinned to the
    BUNDLE's challenge content. A reproduction months later runs against the bundle's exact
    challenge set and hashes — never a silently re-resolved "current" selection. Local corpus
    content is checked per id: any mismatch/missing entry blocks the run (sync the corpus)."""
    det = det_vector(b.get("results", []))
    local = eng_bundle.challenge_hashes(challenges_dir)
    ids, mismatched, missing = [], [], []
    for cid, chash, _ in det:
        ids.append(cid)
        if cid not in local:
            missing.append(cid)
        elif chash and local[cid] != chash:
            mismatched.append(cid)
    m = b.get("model", {})
    sampling = m.get("sampling", {}) or {}
    rb = re.search(r"--reasoning-budget\s+(-?\d+)", m.get("serve_flags") or "")
    return ReproPlan(
        ids=ids,
        suite_id=b.get("suite", {}).get("id", "adhoc"),
        suite_version=str(b.get("suite", {}).get("version", "")),
        family=m.get("family", "(unknown)"),
        artifact=m.get("artifact", "(unknown)"),
        hf_repo=m.get("hf_repo", "(unknown)"),
        file_sha256=m.get("file_sha256", "(none)"),
        max_tokens=sampling.get("max_tokens"),
        context=m.get("context"),
        reasoning_budget=int(rb.group(1)) if rb else None,
        hash_mismatches=mismatched,
        missing=missing,
    )


# --------------------------------------------------------------------------- #
# the verdict
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    """MATCH    — deterministic vectors identical: this run is confirmed on your hardware.
    COMPATIBLE — a handful of rows flipped (GPU nondeterminism happens even at temp 0);
                 informative, listed per challenge, but it never counts as a verification.
    MISMATCH   — more than that: the published result did not reproduce."""
    status: str                        # "MATCH" | "COMPATIBLE" | "MISMATCH"
    n: int                             # size of the original deterministic vector
    flips: list[dict] = field(default_factory=list)   # [{challenge, original, yours}]

    @property
    def ok(self) -> bool:
        return self.status == "MATCH"


# COMPATIBLE tolerance: at most max(1, ceil(COMPAT_FRAC·n)) flipped rows. Deliberately tight —
# "verified" must mean exact, so anything promoted goes through MATCH only.
COMPAT_FRAC = 0.02


def verdict(original: list[dict], reproduction: list[dict]) -> Verdict:
    """Compare two result lists' deterministic vectors. Exact-vector equality (the same predicate
    the server's repro_sig grouping uses) is the only MATCH; a missing or extra row counts as a
    flip like a changed score does."""
    a = {(cid, chash): final for cid, chash, final in det_vector(original)}
    b = {(cid, chash): final for cid, chash, final in det_vector(reproduction)}
    flips = []
    for key in sorted(set(a) | set(b), key=lambda k: k[0]):
        va, vb = a.get(key), b.get(key)
        if va != vb:
            flips.append({"challenge": key[0],
                          "original": va if va is not None else "(absent)",
                          "yours": vb if vb is not None else "(absent)"})
    n = len(a)
    if not flips:
        status = "MATCH"
    elif n > 0 and len(flips) <= max(1, math.ceil(n * COMPAT_FRAC)):
        status = "COMPATIBLE"
    else:
        status = "MISMATCH"
    return Verdict(status=status, n=n, flips=flips)

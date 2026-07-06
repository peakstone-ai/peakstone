"""Server-side truth at ingest (review R2-R5): trust-reconciled family metadata, first-seen
notarization of published_at, suite content-hash comparison, and a content-aware repro sig with
an account-age bar for community verification."""
from __future__ import annotations

import os
import tempfile

_DB = os.path.join(tempfile.mkdtemp(), "test-truth.db")
os.environ.setdefault("PEAKSTONE_DATABASE_URL", f"sqlite:///{_DB}")
os.environ["PEAKSTONE_SKIP_FILE_HASH"] = "1"
os.environ.setdefault("PEAKSTONE_GITHUB_CLIENT_ID", "test_cid")
os.environ.setdefault("PEAKSTONE_GITHUB_CLIENT_SECRET", "test_sec")

import datetime as dt

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from peakstone.engine import bundle, keys
from peakstone.api import identity, ingest, models
from peakstone.api.db import SessionLocal
from peakstone.api.main import app

# Share test_api's OAuth stub when it's loaded in the same process — overwriting the provider's
# exchange with a module-local dict would break whichever module bound accounts first.
try:
    from peakstone.api.tests.test_api import _ACCOUNTS
except ImportError:  # running this file standalone
    _ACCOUNTS = {}
    identity.PROVIDERS["github"].exchange = lambda code, redirect_uri: _ACCOUNTS[code]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _newkey():
    p = Ed25519PrivateKey.generate()
    return p, keys.public_key_b64(p)


def _row(cid, f=1.0):
    return {"model": "m", "challenge": cid, "type": "architecture", "difficulty": 4,
            "scoring": "tests", "final_score": f, "passed": int(f * 10), "total": 10,
            "response": "x", "stdout": "ok"}


def _mk(model, priv, pub, *, ts, ids=("c1", "c2"), vram=24, hashes=None, published=None,
        release_date=None, suite_hash=None):
    """A signed bundle; optional per-challenge content hashes / published_at / suite content_hash
    set post-build (then re-signed) — the ingest checks under test act on the CLAIMED values."""
    b = bundle.produce_bundle(
        {"models": [model], "judge": None, "timestamp": ts,
         "gpu": {"name": "RTX 4090", "driver_version": "595"}},
        [_row(f"{model}-{c}") for c in ids], sign=False)
    for i, r in enumerate(b["results"]):
        if hashes:
            r["challenge_hash"] = hashes[i]
        if published:
            r["published_at"] = published
            r["published_at_source"] = "author"
    if release_date:
        b["model"]["release_date"] = release_date
    if suite_hash:
        b["suite"]["content_hash"] = suite_hash
    b["environment"]["vram_gb"] = vram
    bundle.sign_inplace(b, priv, pub)
    return b


def _bind(client, priv, pub, code, account):
    _ACCOUNTS[code] = account
    nonce = client.post("/account/key-challenge", json={"pubkey": pub}).json()["nonce"]
    r = client.post("/account/bind", json={
        "provider": "github", "pubkey": pub, "nonce": nonce,
        "signature": keys.sign(priv, nonce.encode()), "code": code, "redirect_uri": "http://x/cb"})
    assert r.status_code == 200


# --- R5: the repro sig is content-aware ------------------------------------------------------

def test_repro_sig_includes_challenge_content():
    rows = [{"challenge_id": "a", "challenge_hash": "h1", "score": {"final": 1.0}}]
    same = [{"challenge_id": "a", "challenge_hash": "h1", "score": {"final": 1.0}}]
    other_content = [{"challenge_id": "a", "challenge_hash": "h2", "score": {"final": 1.0}}]
    assert ingest._repro_sig(rows) == ingest._repro_sig(same)
    # same ids + same scores over DIFFERENT challenge content must never verify each other
    assert ingest._repro_sig(rows) != ingest._repro_sig(other_content)


def test_recompute_repro_sigs_restores_formula(client):
    p, pub = _newkey()
    r = client.post("/submissions", json=_mk("resigM", p, pub, ts="resig"))
    assert r.status_code == 201
    with SessionLocal() as db:
        sub = db.scalar(select(models.Submission).where(
            models.Submission.bundle_hash == r.json()["bundle_hash"]))
        good = sub.repro_sig
        sub.repro_sig = "stale-formula"
        db.commit()
        assert ingest.recompute_repro_sigs(db) >= 1
        db.refresh(sub)
        assert sub.repro_sig == good
        assert ingest.recompute_repro_sigs(db) == 0        # idempotent


# --- R5: account-age bar ----------------------------------------------------------------------

def test_fresh_accounts_do_not_community_verify(client, monkeypatch):
    """Two just-minted OAuth accounts agreeing is not verification once the age bar is on; the
    same pair counts after their accounts age past the bar."""
    monkeypatch.setattr(ingest, "COMMUNITY_MIN_ACCOUNT_AGE_DAYS", 7.0)
    (p1, k1), (p2, k2) = _newkey(), _newkey()
    _bind(client, p1, k1, "age-a", {"account_id": "u-age-a", "handle": "age-a"})
    _bind(client, p2, k2, "age-b", {"account_id": "u-age-b", "handle": "age-b"})
    assert client.post("/submissions", json=_mk("ageM", p1, k1, ts="age", vram=24)).status_code == 201
    r2 = client.post("/submissions", json=_mk("ageM", p2, k2, ts="age", vram=25))
    assert r2.status_code == 201
    with SessionLocal() as db:
        subs = db.scalars(select(models.Submission).where(
            models.Submission.suite_version == "age")).all()
        assert {s.trust_tier for s in subs} == {"self-reported"}   # agreed, but too fresh
        # age the accounts past the bar and re-run promotion
        for u in db.scalars(select(models.User)).all():
            u.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8)
        db.flush()
        ingest._recompute_trust(db, subs[0])
        db.commit()
        assert all(s.trust_tier == "community-verified" for s in subs)


# --- R2: family metadata is trust-reconciled ---------------------------------------------------

def test_family_release_date_squat_is_overwritten_by_trust(client, monkeypatch):
    p_squat, k_squat = _newkey()
    r = client.post("/submissions", json=_mk("squatM", p_squat, k_squat, ts="sq1",
                                             release_date="2020-01-01"))    # bogus: everything held-out
    assert r.status_code == 201
    p_op, k_op = _newkey()
    monkeypatch.setattr(ingest, "TRUSTED_PUBKEYS", {k_op})
    r = client.post("/submissions", json=_mk("squatM", p_op, k_op, ts="sq2", vram=25,
                                             release_date="2026-05-01"))    # the real date
    assert r.status_code == 201
    assert client.get("/models/squatM").json()["release_date"] == "2026-05-01"
    # a later self-reported claim can no longer move it
    p3, k3 = _newkey()
    monkeypatch.setattr(ingest, "TRUSTED_PUBKEYS", set())
    r = client.post("/submissions", json=_mk("squatM", p3, k3, ts="sq3", vram=26,
                                             release_date="2019-01-01"))
    assert r.status_code == 201
    assert client.get("/models/squatM").json()["release_date"] == "2026-05-01"


def test_untrusted_lazy_challenge_is_observed_not_published(client):
    p, pub = _newkey()
    assert client.post("/submissions", json=_mk("obsM", p, pub, ts="obs")).status_code == 201
    with SessionLocal() as db:
        ch = db.get(models.Challenge, "obsM-c1")
        assert ch is not None and ch.status == "observed"


# --- R3: published_at is notarized against server first-seen -----------------------------------

def test_future_published_at_is_clamped_to_first_seen(client):
    h = ["a" * 64, "b" * 64]
    p, pub = _newkey()
    r = client.post("/submissions", json=_mk("notarM", p, pub, ts="not1", hashes=h,
                                             published="2027-06-01"))       # claims the future
    assert r.status_code == 201
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    with SessionLocal() as db:
        rows = db.scalars(select(models.Result).where(
            models.Result.challenge_hash.in_(h))).all()
        assert rows and all(x.published_at == today for x in rows)          # clamped: content exists NOW
        assert all(x.published_at_source == "platform-first-seen" for x in rows)


def test_past_published_at_is_kept(client):
    h = ["c" * 64, "d" * 64]
    p, pub = _newkey()
    r = client.post("/submissions", json=_mk("notarP", p, pub, ts="not2", hashes=h,
                                             published="2025-01-01"))       # unfalsifiable, conservative
    assert r.status_code == 201
    with SessionLocal() as db:
        rows = db.scalars(select(models.Result).where(
            models.Result.challenge_hash.in_(h))).all()
        assert rows and all(x.published_at == "2025-01-01" for x in rows)
        assert all(x.published_at_source == "author" for x in rows)


# --- R4: suite content-hash is compared at ingest ----------------------------------------------

def test_suite_hash_mismatch_is_flagged(client):
    p, pub = _newkey()
    r1 = client.post("/submissions", json=_mk("suiteA", p, pub, ts="sh", suite_hash="H1"))
    assert r1.status_code == 201
    # same (suite, version), same challenge-set hash -> agrees
    p2, k2 = _newkey()
    r2 = client.post("/submissions", json=_mk("suiteA", p2, k2, ts="sh", suite_hash="H1", vram=25))
    assert r2.status_code == 201
    # same (suite, version), DIFFERENT challenge set -> flagged, not trusted by name
    p3, k3 = _newkey()
    r3 = client.post("/submissions", json=_mk("suiteB", p3, k3, ts="sh", suite_hash="H2", vram=26))
    assert r3.status_code == 201
    with SessionLocal() as db:
        by_hash = {s.bundle_hash: s for s in db.scalars(select(models.Submission).where(
            models.Submission.suite_version == "sh")).all()}
        assert by_hash[r1.json()["bundle_hash"]].suite_hash_match is None    # first-seen: no basis
        assert by_hash[r2.json()["bundle_hash"]].suite_hash_match is True
        assert by_hash[r3.json()["bundle_hash"]].suite_hash_match is False

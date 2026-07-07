"""The reproduce endpoints (PLAN §12 D): GET /reproduce/{hash} hands back the verbatim signed
bundle (client re-verifies the whole trust chain), /runs/{hash}/reproductions is the public
reproduction record, and the leaderboard's run.reproductions counts by the promotion rule."""
from __future__ import annotations

import os
import tempfile

_DB = os.path.join(tempfile.mkdtemp(), "test-reproduce.db")
os.environ.setdefault("PEAKSTONE_DATABASE_URL", f"sqlite:///{_DB}")
os.environ["PEAKSTONE_SKIP_FILE_HASH"] = "1"
os.environ.setdefault("PEAKSTONE_GITHUB_CLIENT_ID", "test_cid")
os.environ.setdefault("PEAKSTONE_GITHUB_CLIENT_SECRET", "test_sec")

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from peakstone.engine import bundle as eng_bundle
from peakstone.engine import keys, repro
from peakstone.api import identity
from peakstone.api.main import app

try:
    from peakstone.api.tests.test_api import _ACCOUNTS
except ImportError:  # running standalone
    _ACCOUNTS = {}
    identity.PROVIDERS["github"].exchange = lambda code, redirect_uri: _ACCOUNTS[code]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _mk(model="repro-fam", *, finals=(1.0, 0.5), ts="t1"):
    priv = Ed25519PrivateKey.generate()
    pub = keys.public_key_b64(priv)
    rows = [{"model": model, "challenge": f"{model}-c{i}", "type": "basic", "difficulty": 2,
             "scoring": "tests", "final_score": f, "passed": int(f * 10), "total": 10,
             "response": "sol", "stdout": ""} for i, f in enumerate(finals)]
    # a reproduction restamps the ORIGINAL's suite identity (the group key is
    # artifact+suite+vector) — mirror that here; the timestamp still varies the bundle_hash
    b = eng_bundle.produce_bundle(
        {"models": [model], "judge": None, "timestamp": ts,
         "suite_id": f"level-{model}", "suite_version": "1",
         "gpu": {"name": "g", "driver_version": "1"}}, rows, sign=False)
    b["environment"]["vram_gb"] = 24
    eng_bundle.sign_inplace(b, priv, pub)
    return b, priv, pub


def _bind(client, priv, pub, code, account):
    _ACCOUNTS[code] = account
    nonce = client.post("/account/key-challenge", json={"pubkey": pub}).json()["nonce"]
    r = client.post("/account/bind", json={
        "provider": "github", "pubkey": pub, "nonce": nonce,
        "signature": keys.sign(priv, nonce.encode()), "code": code, "redirect_uri": "http://x/cb"})
    assert r.status_code == 200


def test_reproduce_endpoint_roundtrips_verifiable_bundle(client):
    b, _, _ = _mk(ts="rt")
    assert client.post("/submissions", json=b).status_code == 201
    r = client.get(f"/reproduce/{b['bundle_hash']}")
    assert r.status_code == 200
    got = r.json()
    # verbatim: the fetched bundle still passes the FULL client-side trust chain
    assert repro.verify_bundle(got["bundle"]) == []
    assert got["bundle"]["bundle_hash"] == b["bundle_hash"]
    assert got["reproductions"] == 0
    assert client.get("/reproduce/nope").status_code == 404


def test_reproductions_listing_and_verified_count(client):
    """Two bound accounts submit the same deterministic vector: the listing shows the second run
    as an independent reproduction, run.reproductions counts it, and the pair promotes to
    community-verified (the existing ingest rule, observed through the new surfaces)."""
    b1, p1, k1 = _mk("repro-pair", ts="a")
    b2, p2, k2 = _mk("repro-pair", ts="b")
    assert repro.repro_sig(b1["results"]) == repro.repro_sig(b2["results"])  # same vector
    _bind(client, p1, k1, "rp-a", {"account_id": "u-rp-a", "handle": "rp-alice"})
    _bind(client, p2, k2, "rp-b", {"account_id": "u-rp-b", "handle": "rp-bob"})
    assert client.post("/submissions", json=b1).status_code == 201
    assert client.post("/submissions", json=b2).status_code == 201

    r = client.get(f"/runs/{b1['bundle_hash']}/reproductions").json()
    assert r["n"] == 1 and r["distinct_identities"] == 1
    rep = r["reproductions"][0]
    assert rep["bundle_hash"] == b2["bundle_hash"] and rep["submitter"] == "rp-bob"
    assert rep["independent"] is True and rep["vram_gb"] == 24

    lb = client.get("/leaderboard?suite=all").json()
    row = next(x for x in lb["leaderboard"] if x["family"] == "repro-pair")
    assert row["run"]["reproductions"] == 1
    assert row["run"]["trust_tier"] == "community-verified"   # the pair promoted


def test_self_reproduction_is_transparency_not_verification(client):
    """The same account re-running its own bundle shows in the listing but never counts."""
    b1, p1, k1 = _mk("repro-self", ts="s1")
    b2, p2, k2 = _mk("repro-self", ts="s2")         # a different key…
    _bind(client, p1, k1, "rp-self", {"account_id": "u-rp-self", "handle": "solo"})
    _bind(client, p2, k2, "rp-self2", {"account_id": "u-rp-self", "handle": "solo"})  # …same account
    assert client.post("/submissions", json=b1).status_code == 201
    assert client.post("/submissions", json=b2).status_code == 201

    r = client.get(f"/runs/{b1['bundle_hash']}/reproductions").json()
    assert r["n"] == 1 and r["distinct_identities"] == 0
    assert r["reproductions"][0]["independent"] is False
    row = next(x for x in client.get("/leaderboard?suite=all").json()["leaderboard"]
               if x["family"] == "repro-self")
    assert row["run"]["reproductions"] == 0
    assert row["run"]["trust_tier"] == "self-reported"        # no self-promotion

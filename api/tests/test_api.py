"""End-to-end API behavior: trust chain, community-verified promotion, account binding, facets.

Runs against a throwaway SQLite db (env set before the app imports) with a stubbed OAuth provider,
so it needs no network and no real GPUs/models.
"""
from __future__ import annotations

import os
import tempfile

# point the app at an isolated db + enable the github provider BEFORE importing it
_DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["PEAKSTONE_DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["PEAKSTONE_SKIP_FILE_HASH"] = "1"
os.environ["PEAKSTONE_GITHUB_CLIENT_ID"] = "test_cid"
os.environ["PEAKSTONE_GITHUB_CLIENT_SECRET"] = "test_sec"

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from engine import bundle, keys
from api import identity
from api.main import app

# canned OAuth accounts, keyed by the fake "code" we pass to /account/bind
_ACCOUNTS: dict[str, dict] = {}
identity.PROVIDERS["github"].exchange = lambda code, redirect_uri: _ACCOUNTS[code]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _newkey():
    p = Ed25519PrivateKey.generate()
    return p, keys.public_key_b64(p)


def _result(cid, typ, f, metrics=None):
    r = {"model": "m", "challenge": cid, "type": typ, "difficulty": 4, "scoring": "tests",
         "final_score": f, "passed": int(f * 10), "total": 10, "tok_per_s": 50,
         "response": "x", "stdout": "ok"}
    if metrics:
        r["metrics"] = metrics
    return r


def _bundle(model, finals, vram, priv, pub, suite_ts):
    """A signed bundle. A reproduction set shares suite_ts (same suite); vram varies the hardware so
    the content-address differs (otherwise the second submission would dedupe)."""
    b = bundle.produce_bundle(
        {"models": [model], "judge": None, "timestamp": suite_ts,
         "gpu": {"name": "RTX 4090", "driver_version": "595"}},
        [_result(f"arch-{i}", "architecture", f) for i, f in enumerate(finals)]
        + [_result("refuse-x", "refusal", 1.0)],
        sign=False)
    b["environment"]["vram_gb"] = vram
    b["bundle_hash"] = bundle._sha256_bytes(bundle.canonical_bytes(bundle._without_sig(b)))
    b["submitter"] = {"pubkey": pub, "signature": keys.sign(priv, b["bundle_hash"].encode())}
    return b


def _tiers(client, family):
    return sorted({r["run"]["trust_tier"] for r in client.get(f"/models/{family}").json()["runs"]})


def _bind(client, priv, pub, code, account):
    _ACCOUNTS[code] = account
    nonce = client.post("/account/key-challenge", json={"pubkey": pub}).json()["nonce"]
    return client.post("/account/bind", json={
        "provider": "github", "pubkey": pub, "nonce": nonce,
        "signature": keys.sign(priv, nonce.encode()), "code": code, "redirect_uri": "http://x/cb"})


def test_submission_trust_chain(client):
    ap, a = _newkey()
    r = client.post("/submissions", json=_bundle("trustX", [0.5], 24, ap, a, "s"))
    assert r.status_code == 201 and r.json()["trust_tier"] == "self-reported"
    # tampering with a stored score breaks the content-address -> 400
    bad = _bundle("trustX", [0.5], 24, ap, a, "s2")
    bad["results"][0]["score"]["final"] = 0.99
    assert client.post("/submissions", json=bad).status_code == 400
    # exact replay -> 409 dedupe
    again = _bundle("trustDup", [0.5], 24, ap, a, "s3")
    assert client.post("/submissions", json=again).status_code == 201
    assert client.post("/submissions", json=again).status_code == 409


def test_community_verified_promotion(client):
    ap, a = _newkey(); bp, b = _newkey()
    client.post("/submissions", json=_bundle("modelX", [0.5, 0.5, 0.5], 24, ap, a, "X"))
    assert _tiers(client, "modelX") == ["self-reported"]
    # a second, distinct identity reproduces the same deterministic result vector -> both promoted
    client.post("/submissions", json=_bundle("modelX", [0.5, 0.5, 0.5], 16, bp, b, "X"))
    assert _tiers(client, "modelX") == ["community-verified"]
    # a divergent result (different scores) is NOT a reproduction -> stays self-reported
    cp, c = _newkey()
    client.post("/submissions", json=_bundle("modelX", [0.9, 0.9, 0.9], 24, cp, c, "X"))
    divergent = [r for r in client.get("/models/modelX").json()["runs"] if r["code_score"] > 0.8][0]
    assert divergent["run"]["trust_tier"] == "self-reported"


def test_account_binding_and_submitter_handle(client):
    ap, a = _newkey()
    assert _bind(client, ap, a, "code_alice", {"account_id": "gh-alice", "handle": "alice"}).status_code == 200
    acct = client.get("/account", params={"pubkey": a}).json()
    assert acct["handle"] == "alice" and acct["providers"][0]["provider"] == "github"
    client.post("/submissions", json=_bundle("modelY", [0.9], 24, ap, a, "Y"))
    assert client.get("/models/modelY").json()["runs"][0]["run"]["submitter"] == "alice"


def test_binding_rejects_bad_and_reused_proof(client):
    ap, a = _newkey()
    _ACCOUNTS["code_x"] = {"account_id": "gh-x", "handle": "x"}
    nonce = client.post("/account/key-challenge", json={"pubkey": a}).json()["nonce"]
    # wrong signature
    bad = client.post("/account/bind", json={"provider": "github", "pubkey": a, "nonce": nonce,
                      "signature": keys.sign(ap, b"not-the-nonce"), "code": "code_x", "redirect_uri": "x"})
    assert bad.status_code == 400
    # the nonce was consumed by the failed attempt -> cannot be reused
    reuse = client.post("/account/bind", json={"provider": "github", "pubkey": a, "nonce": nonce,
                        "signature": keys.sign(ap, nonce.encode()), "code": "code_x", "redirect_uri": "x"})
    assert reuse.status_code == 400


def test_anti_self_verify_one_account_counts_once(client):
    dp, d = _newkey(); ep, e = _newkey()
    assert _bind(client, dp, d, "code_bob", {"account_id": "gh-bob", "handle": "bob"}).status_code == 200
    assert _bind(client, ep, e, "code_bob", {"account_id": "gh-bob", "handle": "bob"}).status_code == 200
    # two keys, same bound account -> a single reproduction identity -> no promotion
    client.post("/submissions", json=_bundle("modelZ", [0.7, 0.7], 24, dp, d, "Z"))
    client.post("/submissions", json=_bundle("modelZ", [0.7, 0.7], 16, ep, e, "Z"))
    assert _tiers(client, "modelZ") == ["self-reported"]


def test_provider_gating(client):
    cid = os.environ.pop("PEAKSTONE_GITHUB_CLIENT_ID")
    try:
        assert client.get("/auth/github/authorize-url", params={"redirect_uri": "x"}).status_code == 503
    finally:
        os.environ["PEAKSTONE_GITHUB_CLIENT_ID"] = cid
    url = client.get("/auth/github/authorize-url",
                     params={"redirect_uri": "http://app/cb", "state": "s"}).json()["authorize_url"]
    assert url.startswith("https://github.com/login/oauth/authorize?")


def test_facets_and_challenges(client):
    fp, f = _newkey()
    client.post("/submissions", json=_bundle("facetM", [1.0, 0.0], 24, fp, f, "F"))
    fac = client.get("/facets").json()
    assert "self-reported" in fac["trust_tiers"]
    assert any(s["name"] == "adhoc" for s in fac["suites"])
    chs = client.get("/challenges").json()
    assert chs["count"] >= 1
    det = client.get("/challenges/arch-0").json()
    assert det["n_families"] >= 1 and det["results"][0]["score"] >= det["results"][-1]["score"]
    assert client.get("/challenges/does-not-exist").status_code == 404


def _metric_bundle(model, loc, rss, priv, pub):
    b = bundle.produce_bundle(
        {"models": [model], "judge": None, "timestamp": "EFF",
         "gpu": {"name": "RTX 4090", "driver_version": "595"}},
        [_result("eff-0", "architecture", 1.0, {"loc": loc, "peak_rss_mb": rss, "test_wall_s": 0.1})],
        sign=False)
    b["bundle_hash"] = bundle._sha256_bytes(bundle.canonical_bytes(bundle._without_sig(b)))
    b["submitter"] = {"pubkey": pub, "signature": keys.sign(priv, b["bundle_hash"].encode())}
    return b


def test_efficiency_metrics_aggregation_and_sort(client):
    lean_p, lean = _newkey()      # small, lean solution
    bloat_p, bloat = _newkey()    # correct but bloated
    assert client.post("/submissions", json=_metric_bundle("leanModel", 10, 30.0, lean_p, lean)).status_code == 201
    assert client.post("/submissions", json=_metric_bundle("bloatModel", 90, 300.0, bloat_p, bloat)).status_code == 201

    # both are equally correct (code_score 1.0) -> default ranking is tie-ish; sort by loc asc separates
    lb = client.get("/leaderboard", params={"sort": "loc", "order": "asc"}).json()
    fams = [r["family"] for r in lb["leaderboard"] if r["family"] in ("leanModel", "bloatModel")]
    assert fams == ["leanModel", "bloatModel"], fams
    # metrics are aggregated onto the row
    lean_row = next(r for r in lb["leaderboard"] if r["family"] == "leanModel")
    assert lean_row["metrics"]["loc"] == 10 and lean_row["metrics"]["peak_rss_mb"] == 30.0
    # sorting respects order: rss desc puts the bloated one first
    lb2 = client.get("/leaderboard", params={"sort": "peak_rss_mb", "order": "desc"}).json()
    fams2 = [r["family"] for r in lb2["leaderboard"] if r["family"] in ("leanModel", "bloatModel")]
    assert fams2 == ["bloatModel", "leanModel"], fams2
    # the axes are advertised in facets
    assert any(a["key"] == "loc" for a in client.get("/facets").json()["sort_axes"])

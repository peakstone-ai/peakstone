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

from peakstone.engine import bundle, keys
from peakstone.api import identity, proposals
from peakstone.api.main import app

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


def _result(cid, typ, f, metrics=None, ctoks=None, ptoks=None):
    r = {"model": "m", "challenge": cid, "type": typ, "difficulty": 4, "scoring": "tests",
         "final_score": f, "passed": int(f * 10), "total": 10, "tok_per_s": 50, "latency_s": 2.0,
         "response": "x", "stdout": "ok"}
    if metrics:
        r["metrics"] = metrics
    if ctoks is not None:
        r["completion_tokens"] = ctoks
    if ptoks is not None:
        r["prompt_tokens"] = ptoks
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
    bundle.sign_inplace(b, priv, pub)
    return b


def _tiers(client, family):
    return sorted({r["run"]["trust_tier"] for r in client.get(f"/models/{family}").json()["runs"]})


def _bind(client, priv, pub, code, account):
    _ACCOUNTS[code] = account
    nonce = client.post("/account/key-challenge", json={"pubkey": pub}).json()["nonce"]
    return client.post("/account/bind", json={
        "provider": "github", "pubkey": pub, "nonce": nonce,
        "signature": keys.sign(priv, nonce.encode()), "code": code, "redirect_uri": "http://x/cb"})


def _heldout_bundle(model, priv, pub, *, release_date, published_at, n=6, ts="ho"):
    """A signed bundle with enough CLEAN results (published_at > release_date) to qualify for the
    ranked held-out tier. release_date/published_at are set after build, then re-signed."""
    b = bundle.produce_bundle(
        {"models": [model], "judge": None, "timestamp": ts,
         "gpu": {"name": "RTX 4090", "driver_version": "595"}},
        [_result(f"{model}-c{i}", "architecture", 1.0) for i in range(n)], sign=False)
    b["model"]["release_date"] = release_date
    for r in b["results"]:
        r["published_at"] = published_at
    b["environment"]["vram_gb"] = 24
    bundle.sign_inplace(b, priv, pub)
    return b


def test_held_out_ranked_requires_trust(client, monkeypatch):
    """Review M2: a self-reported run can't reach the ranked held-out tier on forged dates alone;
    only an operator (runner-verified) or independently-reproduced run ranks."""
    from peakstone.api import ingest
    sp, s = _newkey()
    r = client.post("/submissions", json=_heldout_bundle("selfHO", sp, s,
                                                          release_date="2020-01-01", published_at="2026-01-01"))
    assert r.status_code == 201 and r.json()["trust_tier"] == "self-reported"
    tp, t = _newkey()
    monkeypatch.setattr(ingest, "TRUSTED_PUBKEYS", {t})           # operator key
    r = client.post("/submissions", json=_heldout_bundle("trustHO", tp, t,
                                                         release_date="2020-01-01", published_at="2026-01-01"))
    assert r.status_code == 201 and r.json()["trust_tier"] == "runner-verified"
    byfam = {row["family"]: row for row in client.get("/leaderboard").json()["leaderboard"]}
    assert byfam["trustHO"]["held_out_status"] == "ranked"        # trusted + clean evidence -> ranks
    assert byfam["selfHO"]["held_out_status"] == "provisional"    # same forged dates, but can't rank


def test_run_results_and_transcript(client):
    """The web run-explorer contract: /runs/{hash} carries model header + per-challenge rows, and
    /runs/{hash}/challenge/{id} returns that challenge's transcript (the proposed solution)."""
    ap, a = _newkey()
    b = _bundle("runX", [0.5], 27, ap, a, "run-ts")
    assert client.post("/submissions", json=b).status_code == 201
    h = b["bundle_hash"]
    run = client.get(f"/runs/{h}").json()
    assert run["family"] == "runX" and run["artifact"] and run["trust_tier"] == "self-reported"
    assert run["results"] and all("final" in r for r in run["results"])
    cid = run["results"][0]["challenge"]
    tr = client.get(f"/runs/{h}/challenge/{cid}").json()
    assert tr["challenge"] == cid and tr["transcript"]["raw_output"] == "x"   # the model's answer


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


def test_truncation_rate():
    from types import SimpleNamespace as NS
    from peakstone.api.main import _truncation, _agg_metrics
    rs = [
        NS(final=0.0, metrics={"trunc_truncated": 1.0}),   # cut off at the budget
        NS(final=1.0, metrics={"trunc_truncated": 0.0}),   # finished on its own
        NS(final=0.0, metrics={"trunc_truncated": 1.0}),
        NS(final=0.5, metrics={}),                          # not a generated challenge -> not counted
    ]
    t = _truncation(rs)
    assert t["truncation_rate"] == 0.667 and t["n_generated"] == 3   # 2 of 3 generated were truncated
    assert _truncation([NS(final=1.0, metrics={})]) == {"truncation_rate": None, "n_generated": 0}
    # the probe key must NOT leak into the leanness/efficiency averages
    assert "trunc_truncated" not in _agg_metrics(rs)


def test_reasoning_budget_parsing():
    """The thinking-budget facet reads the served --reasoning-budget: 0=off, -1=full, N=capped, None
    if the flag wasn't set. Lets the leaderboard split a model's runs by thinking budget."""
    from types import SimpleNamespace as NS
    from peakstone.api.main import _submission_reasoning_budget as b
    assert b(NS(serve_flags="-fa --reasoning-budget 4096 -c 16384")) == 4096
    assert b(NS(serve_flags="--reasoning-budget 0")) == 0
    assert b(NS(serve_flags="--reasoning-budget -1")) == -1
    assert b(NS(serve_flags="-fa -c 16384")) is None and b(NS(serve_flags=None)) is None


def test_ctx_efficiency():
    from types import SimpleNamespace as NS
    from peakstone.api.main import _ctx_efficiency
    rs = [
        NS(final=1.0, metrics={"tokens_to_solve": 1000, "gen_tokens": 300, "ctx_limited": 0}),
        NS(final=0.5, metrics={"tokens_to_solve": 3000, "gen_tokens": 2500, "ctx_limited": 0}),
        NS(final=0.0, metrics={"tokens_to_solve": 8000, "gen_tokens": 7000, "ctx_limited": 1}),  # excluded
        NS(final=0.9, metrics={}),                                                               # unmeasured
    ]
    e = _ctx_efficiency(rs)
    # honest like-for-like: mean over the 2 non-limited measured results (final .75, tokens 2000)
    assert e["score_per_1k_tokens"] == 0.375          # 0.75 / (2000/1000)
    assert e["tokens_to_solve"] == 2000 and e["gen_tokens"] == 1400
    assert e["n_ctx_limited"] == 1                     # the truncated result is flagged, not averaged in
    assert e["reasoning_tokens"] is None              # server never reported it


def test_ctx_efficiency_on_leaderboard(client):
    ap, a = _newkey()
    b = bundle.produce_bundle(
        {"models": ["effm"], "judge": None, "timestamp": "effts",
         "gpu": {"name": "RTX 4090", "driver_version": "595"}},
        [_result("arch-0", "architecture", 1.0, ctoks=300, ptoks=700),    # 1000 tok
         _result("arch-1", "architecture", 0.5, ctoks=2500, ptoks=500)],  # 3000 tok
        sign=False)
    bundle.sign_inplace(b, ap, a)
    assert client.post("/submissions", json=b).status_code == 201
    row = next(r for r in client.get("/leaderboard").json()["leaderboard"] if r["family"] == "effm")
    assert row["tokens_to_solve"] == 2000                  # mean of 1000 + 3000
    assert row["score_per_1k_tokens"] == 0.375             # mean final .75 / (2000/1000)
    assert row["n_ctx_limited"] == 0
    assert client.get("/leaderboard", params={"sort": "score_per_1k_tokens"}).status_code == 200


def test_long_context_axis(client):
    ap, a = _newkey()
    b = bundle.produce_bundle(
        {"models": ["lcm"], "judge": None, "timestamp": "lcts",
         "gpu": {"name": "RTX 4090", "driver_version": "595"}},
        [_result("arch-0", "architecture", 0.2),                     # code axis
         _result("lc-01-buried-routes", "long-context", 1.0)],       # long-context axis
        sign=False)
    bundle.sign_inplace(b, ap, a)
    assert client.post("/submissions", json=b).status_code == 201
    row = next(r for r in client.get("/leaderboard").json()["leaderboard"] if r["family"] == "lcm")
    assert row["long_ctx_score"] == 1.0 and row["n_long_ctx"] == 1   # its own axis
    assert row["code_score"] == 0.2                                  # long-context excluded from code
    assert client.get("/leaderboard", params={"sort": "long_ctx_score"}).status_code == 200


def test_coverage_and_sol_per_s(client):
    ap, a = _newkey()
    # 3 arch challenges + 1 refusal = 4 results, each latency 2.0s -> sol/s = 4 / 8 = 0.5
    assert client.post("/submissions", json=_bundle("covX", [0.6, 0.6, 0.6], 24, ap, a, "cov")).status_code == 201
    row = next(r for r in client.get("/leaderboard").json()["leaderboard"] if r["family"] == "covX")
    assert row["n_total"] == 4                      # coverage: challenges in the run
    assert row["sol_per_s"] == 0.5                  # throughput over total model time
    assert row["total_time_s"] == 8.0               # total run time = sum of per-challenge latency
    assert row["run"]["vram_gb"] == 24 and "ram_gb" in row["run"]   # machine totals
    assert "vram_used_gb" in row["run"] and "ram_used_gb" in row["run"]   # model footprint exposed
    assert row["run"]["gpu"] == "RTX 4090" and "cpu" in row["run"]        # hardware it ran on
    # sortable axis
    assert client.get("/leaderboard", params={"sort": "sol_per_s"}).status_code == 200


def test_leaderboard_collapse_quant(client):
    ap, a = _newkey()

    def mk(artifact, sha, f):
        b = bundle.produce_bundle({"models": ["qz"], "judge": None, "timestamp": artifact,
                                   "gpu": {"name": "RTX 4090"}},
                                  [_result(f"qz-{i}", "architecture", f) for i in range(2)], sign=False)
        b["model"]["family"], b["model"]["artifact"], b["model"]["file_sha256"] = "qz", artifact, sha
        bundle.sign_inplace(b, ap, a)
        return b

    assert client.post("/submissions", json=mk("UD-Q4_K_XL", "s4", 0.6)).status_code == 201
    assert client.post("/submissions", json=mk("UD-Q6_K", "s6", 0.7)).status_code == 201
    # default: family collapses to its best quant -> one row
    fam = [r for r in client.get("/leaderboard").json()["leaderboard"] if r["family"] == "qz"]
    assert len(fam) == 1 and fam[0]["run"]["artifact"] == "UD-Q6_K"
    # collapse=quant: both quants as separate rows
    pq = [r for r in client.get("/leaderboard", params={"collapse": "quant"}).json()["leaderboard"]
          if r["family"] == "qz"]
    assert {r["run"]["artifact"] for r in pq} == {"UD-Q4_K_XL", "UD-Q6_K"}


def test_leaderboard_prefers_most_coverage(client):
    ap, a = _newkey()

    def mk(sha, n, f):
        b = bundle.produce_bundle({"models": ["covm"], "judge": None, "timestamp": sha,
                                   "gpu": {"name": "RTX 4090"}},
                                  [_result(f"cm-{i}", "architecture", f) for i in range(n)], sign=False)
        b["model"]["family"], b["model"]["artifact"], b["model"]["file_sha256"] = "covm", "Q4", sha
        bundle.sign_inplace(b, ap, a)
        return b

    # a small high-scoring run, then a more thorough lower-scoring one of the same model+quant
    assert client.post("/submissions", json=mk("smoke", 2, 0.9)).status_code == 201
    assert client.post("/submissions", json=mk("deep", 10, 0.6)).status_code == 201
    row = next(r for r in client.get("/leaderboard").json()["leaderboard"] if r["family"] == "covm")
    assert row["n_total"] == 10 and row["code_score"] == 0.6   # the most-coverage run is shown, not the best score


def test_run_results_endpoint(client):
    ap, a = _newkey()
    assert client.post("/submissions", json=_bundle("runres", [0.5, 1.0], 24, ap, a, "rr")).status_code == 201
    bh = next(r for r in client.get("/leaderboard").json()["leaderboard"]
              if r["family"] == "runres")["run"]["bundle_hash"]
    res = client.get(f"/runs/{bh}").json()
    by_ch = {r["challenge"]: r for r in res["results"]}
    assert {"arch-0", "arch-1", "refuse-x"} <= set(by_ch)       # per-challenge breakdown of the run
    assert "transcript" not in by_ch["arch-0"]                  # lite: no bulky transcript in the list
    full = client.get(f"/runs/{bh}/challenge/arch-0").json()    # transcript fetched on demand
    assert full["transcript"]["raw_output"] == "x" and full["transcript"]["stdout"] == "ok"
    assert client.get("/runs/nope").status_code == 404
    assert client.get(f"/runs/{bh}/challenge/nope").status_code == 404


def test_pubkey_swap_is_rejected(client):
    ap, a = _newkey()
    b = _bundle("pubkeyM", [0.5], 24, ap, a, "PK")
    b["submitter"]["pubkey"] = _newkey()[1]      # re-attribute someone's run by swapping the pubkey
    # the pubkey is bound into bundle_hash, so the server's re-hash no longer matches -> rejected
    assert client.post("/submissions", json=b).status_code == 400


def test_community_verified_promotion(client):
    ap, a = _newkey(); bp, b = _newkey()
    # Sybil resistance: promotion needs distinct BOUND accounts, so bind the two keys first
    assert _bind(client, ap, a, "cv-a", {"account_id": "cv-acct-a", "handle": "cva"}).status_code == 200
    assert _bind(client, bp, b, "cv-b", {"account_id": "cv-acct-b", "handle": "cvb"}).status_code == 200
    client.post("/submissions", json=_bundle("modelX", [0.5, 0.5, 0.5], 24, ap, a, "X"))
    assert _tiers(client, "modelX") == ["self-reported"]
    # a second, distinct bound identity reproduces the same deterministic result vector -> both promoted
    client.post("/submissions", json=_bundle("modelX", [0.5, 0.5, 0.5], 16, bp, b, "X"))
    assert _tiers(client, "modelX") == ["community-verified"]
    # a divergent result (different scores) is NOT a reproduction -> stays self-reported
    cp, c = _newkey()
    client.post("/submissions", json=_bundle("modelX", [0.9, 0.9, 0.9], 24, cp, c, "X"))
    divergent = [r for r in client.get("/models/modelX").json()["runs"] if r["code_score"] > 0.8][0]
    assert divergent["run"]["trust_tier"] == "self-reported"


def test_rejects_non_finite_score(client):
    import json
    import math
    ap, a = _newkey()
    b = _bundle("nanModel", [0.5], 24, ap, a, "NF")
    # NaN slips through the schema's min/max (all NaN comparisons are False) but must be rejected
    b["results"][0]["score"]["final"] = math.nan
    bundle.sign_inplace(b, ap, a)              # re-sign over the mutated content
    # post raw JSON (json.dumps emits `Infinity`; the test client's json= would refuse to serialize it)
    r = client.post("/submissions", content=json.dumps(b), headers={"content-type": "application/json"})
    assert r.status_code == 400 and "non-finite" in r.json()["detail"]
    # the guard must also cover metrics/latency_s/tok_per_s — these reach the public aggregates + the
    # response, where Starlette renders with allow_nan=False (a single NaN row = persistent 500 DoS)
    b2 = _bundle("nanMetric", [0.5], 25, ap, a, "NF2")
    b2["results"][0]["metrics"] = {"peak_rss_mb": math.inf}
    bundle.sign_inplace(b2, ap, a)
    r2 = client.post("/submissions", content=json.dumps(b2), headers={"content-type": "application/json"})
    assert r2.status_code == 400 and "metrics" in r2.json()["detail"]


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
    bundle.sign_inplace(b, priv, pub)
    return b


def _proposal(slug, priv, pub, *, with_tests=True, with_ref=True):
    p = {"proposal_version": "1", "slug": slug, "title": slug.upper(), "language": "python",
         "category": "basics", "difficulty": 2, "scoring": "tests", "solution_file": "solution.py",
         "timeout": 30, "spec": f"# {slug}\nImplement it.", "files": {"meta.toml": f"id='{slug}'"}}
    if with_tests:
        p["files"]["tests/test_x.py"] = "def test(): assert True"
    if with_ref:
        p["files"]["reference/solution.py"] = "value = 1"
    p["content_hash"] = proposals._content_hash(p)
    p["validation"] = {"reference_passes": True, "passed": 1, "total": 1}
    p["submitter"] = {"pubkey": pub, "signature": keys.sign(priv, p["content_hash"].encode())}
    return p


def _as_admin(pub):
    os.environ["PEAKSTONE_ADMIN_KEYS"] = pub


def test_proposal_validation_and_dedupe(client):
    ap, a = _newkey()
    assert client.post("/proposals", json=_proposal("py-prop-1", ap, a)).status_code == 201
    # dedupe on content_hash
    assert client.post("/proposals", json=_proposal("py-prop-1", ap, a)).status_code == 409
    # missing tests / reference / bad sig -> 400
    assert client.post("/proposals", json=_proposal("py-no-tests", ap, a, with_tests=False)).status_code == 400
    assert client.post("/proposals", json=_proposal("py-no-ref", ap, a, with_ref=False)).status_code == 400
    bad = _proposal("py-bad-sig", ap, a)
    bad["submitter"]["signature"] = keys.sign(ap, b"wrong")
    assert client.post("/proposals", json=bad).status_code == 400
    tampered = _proposal("py-tampered", ap, a)
    tampered["difficulty"] = 5  # changes content but not the recorded hash
    assert client.post("/proposals", json=tampered).status_code == 400


def test_challenge_moderation_flow(client):
    author_p, author = _newkey()
    admin_p, admin = _newkey()
    r = client.post("/proposals", json=_proposal("py-moderate", author_p, author))
    pid = r.json()["id"]
    # appears in the pending queue
    assert any(p["slug"] == "py-moderate" for p in client.get("/proposals").json()["proposals"])
    # full proposal carries spec + files for review
    detail = client.get(f"/proposals/{pid}").json()
    assert "tests/test_x.py" in detail["files"] and detail["spec"].startswith("# py-moderate")

    # non-admin review -> 403
    _as_admin(admin)
    nonadmin = client.post(f"/proposals/{pid}/review", json={
        "pubkey": author, "signature": keys.sign(author_p, f"approve:{r.json()['content_hash']}".encode()),
        "decision": "approve"})
    assert nonadmin.status_code == 403
    # admin approves (signs "<decision>:<content_hash>")
    chash = r.json()["content_hash"]
    ok = client.post(f"/proposals/{pid}/review", json={
        "pubkey": admin, "signature": keys.sign(admin_p, f"approve:{chash}".encode()),
        "decision": "approve", "note": "lgtm"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    # a published, attributed Challenge now exists
    ch = next(c for c in client.get("/challenges").json()["challenges"] if c["id"] == "py-moderate")
    assert ch["status"] == "published" and ch["title"] == "PY-MODERATE" and ch["version"] == 1
    # re-reviewing the same proposal -> 409
    assert client.post(f"/proposals/{pid}/review", json={
        "pubkey": admin, "signature": keys.sign(admin_p, f"approve:{chash}".encode()),
        "decision": "approve"}).status_code == 409

    # deprecate (admin-signed, version-bound) flips status; non-admin can't
    assert client.post("/challenges/py-moderate/deprecate", json={
        "pubkey": author, "signature": keys.sign(author_p, b"deprecate:py-moderate:1"),
        "decision": "x"}).status_code == 403
    dep = client.post("/challenges/py-moderate/deprecate", json={
        "pubkey": admin, "signature": keys.sign(admin_p, b"deprecate:py-moderate:1")})
    assert dep.status_code == 200 and dep.json()["deprecated"] is True


def test_proposal_reject(client):
    author_p, author = _newkey()
    admin_p, admin = _newkey()
    _as_admin(admin)
    r = client.post("/proposals", json=_proposal("py-reject", author_p, author))
    pid, chash = r.json()["id"], r.json()["content_hash"]
    rej = client.post(f"/proposals/{pid}/review", json={
        "pubkey": admin, "signature": keys.sign(admin_p, f"reject:{chash}".encode()),
        "decision": "reject", "note": "off topic"})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    # rejection does NOT publish a challenge
    assert not any(c["id"] == "py-reject" for c in client.get("/challenges").json()["challenges"])


def _env_bundle(model, passed, priv, pub):
    rows = [{"model": "m", "challenge": f"env-{i}", "type": "goal-state-env",
             "verification": "goal-state-env", "scoring": "goal-state", "difficulty": 3,
             "final_score": 1.0 if passed else 0.0, "passed": int(passed), "total": 1,
             "response": "x", "stdout": "",
             "env": {"provider": "local", "checks": [{"name": "goal", "ok": passed}]}}
            for i in range(2)]
    b = bundle.produce_bundle({"models": [model], "judge": None, "timestamp": "AG",
                              "gpu": {"name": "RTX 4090", "driver_version": "595"}}, rows, sign=False)
    bundle.sign_inplace(b, priv, pub)
    return b


def test_agentic_axis_is_separate_from_coding(client):
    cp, c = _newkey(); ap, a = _newkey()
    client.post("/submissions", json=_bundle("coderOnly", [0.8, 0.8], 24, cp, c, "AX"))
    assert client.post("/submissions", json=_env_bundle("agentOnly", True, ap, a)).status_code == 201

    # goal-state-env results land in their OWN axis, not folded into code_score
    code_board = client.get("/leaderboard").json()["leaderboard"]
    coder = next(r for r in code_board if r["family"] == "coderOnly")
    assert coder["agent_score"] is None                     # a coder has no agentic runs
    assert not any(r["family"] == "agentOnly" for r in code_board)  # agent-only isn't on the code board

    # faceting by agent_score surfaces the agentic run with its score
    agent_board = client.get("/leaderboard", params={"sort": "agent_score"}).json()["leaderboard"]
    agent = next(r for r in agent_board if r["family"] == "agentOnly")
    assert agent["agent_score"] == 1.0 and agent["n_agent"] == 2
    assert not any(r["family"] == "coderOnly" for r in agent_board)  # a coder isn't on the agent board
    assert any(x["key"] == "agent_score" for x in client.get("/facets").json()["sort_axes"])
    # the env challenges were registered in the corpus with goal-state-env verification
    chs = {c["id"]: c for c in client.get("/challenges").json()["challenges"]}
    assert chs["env-0"]["verification"] == "goal-state-env"


def _planner_bundle(model, score, priv, pub):
    rows = [{"model": "m", "challenge": f"plan-{i}", "type": "planner", "category": "planner",
             "verification": "deterministic-tests", "scoring": "tests", "difficulty": 4,
             "final_score": score, "passed": int(score * 10), "total": 10, "response": "x",
             "stdout": "ok", "env": {"role": "planner", "coder_model": "qwen3-coder"}}
            for i in range(2)]
    b = bundle.produce_bundle({"models": [model], "judge": None, "timestamp": "PL",
                              "gpu": {"name": "RTX 4090", "driver_version": "595"}}, rows, sign=False)
    bundle.sign_inplace(b, priv, pub)
    return b


def test_planner_axis_is_separate_from_coding(client):
    pp, p = _newkey()
    assert client.post("/submissions", json=_planner_bundle("plannerOnly", 0.9, pp, p)).status_code == 201
    # planner runs are NOT on the code board, and don't count as code
    assert not any(r["family"] == "plannerOnly" for r in client.get("/leaderboard").json()["leaderboard"])
    board = client.get("/leaderboard", params={"sort": "planner_score"}).json()["leaderboard"]
    row = next(r for r in board if r["family"] == "plannerOnly")
    assert row["planner_score"] == 0.9 and row["n_planner"] == 2 and row["code_score"] is None
    assert any(x["key"] == "planner_score" for x in client.get("/facets").json()["sort_axes"])


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


def test_observed_capabilities_from_runs(client):
    """A bundle whose results show tool engagement + an agentic resolve -> family.observed_capabilities."""
    ap, a = _newkey()
    rows = [
        {"model": "capM", "challenge": "tool-1", "type": "tool-calling", "scoring": "tool_calls",
         "final_score": 1.0, "passed": 1, "total": 1, "response": "x"},
        {"model": "capM", "challenge": "agent-1", "type": "goal-state-env",
         "verification": "goal-state-env", "scoring": "goal-state", "final_score": 1.0,
         "passed": 1, "total": 1, "response": "x", "env": {"provider": "docker"}},
    ]
    b = bundle.produce_bundle({"models": ["capM"], "judge": None, "timestamp": "C",
                               "gpu": {"name": "RTX 4090", "driver_version": "595"}}, rows, sign=False)
    bundle.sign_inplace(b, ap, a)
    assert client.post("/submissions", json=b).status_code == 201
    obs = client.get("/models/capM").json()["observed_capabilities"]
    assert "tools" in obs and "agentic" in obs


def test_not_capable_verdict_on_leaderboard(client):
    """A non-viable run (looped out of every category) submits as negative data and surfaces on the
    leaderboard with run_status='not_capable' on its run, filterable via ?verdict=."""
    ap, a = _newkey()
    b = bundle.produce_bundle(
        {"models": ["dudcfg"], "judge": None, "timestamp": "nc",
         "gpu": {"name": "RTX 4090", "driver_version": "595"},
         "run_status": "not_capable", "abandoned_categories": ["python", "go"],
         "run_verdict": {"reason": "repetition_loops",
                         "abandoned_categories": ["python", "go"], "loop_streak": 3}},
        [_result("arch-0", "architecture", 0.0), _result("arch-1", "architecture", 0.0)],
        sign=False)
    b["environment"]["vram_gb"] = 24
    bundle.sign_inplace(b, ap, a)
    assert client.post("/submissions", json=b).status_code == 201

    row = next(r for r in client.get("/leaderboard").json()["leaderboard"] if r["family"] == "dudcfg")
    assert row["run"]["run_status"] == "not_capable"
    assert row["run"]["abandoned_categories"] == ["python", "go"]

    only = client.get("/leaderboard", params={"verdict": "not_capable"}).json()["leaderboard"]
    assert only and all(r["run"]["run_status"] == "not_capable" for r in only)
    viable = client.get("/leaderboard", params={"verdict": "viable"}).json()["leaderboard"]
    assert all(r["family"] != "dudcfg" for r in viable)


def test_xz_upload_accepted(client):
    """Bundles are uploaded xz-compressed (Content-Encoding: xz); the middleware decompresses them.
    (Plain uncompressed bodies still parse — every other test posts JSON directly.)"""
    import json as _json
    import lzma as _xz
    ap, a = _newkey()
    b = _bundle("xzm", [0.5], 24, ap, a, "xz")
    raw = _xz.compress(_json.dumps(b).encode())
    r = client.post("/submissions", content=raw,
                    headers={"content-type": "application/json", "content-encoding": "xz"})
    assert r.status_code == 201 and r.json()["n_results"] >= 1
    # a corrupt xz body is a clean 400, not a 500
    bad = client.post("/submissions", content=b"not-xz",
                      headers={"content-type": "application/json", "content-encoding": "xz"})
    assert bad.status_code == 400


def test_xz_zip_bomb_rejected(client):
    """A small body that decompresses past the cap is rejected (413), not allowed to exhaust memory."""
    import lzma as _xz
    bomb = _xz.compress(b"\x00" * (256 * 1024 * 1024))   # ~256 MB of zeros -> tiny xz
    assert len(bomb) < 1_000_000                          # the bomb is small on the wire
    r = client.post("/submissions", content=bomb,
                    headers={"content-type": "application/json", "content-encoding": "xz"})
    assert r.status_code == 413


def test_uncompressed_oversized_body_rejected(client, monkeypatch):
    """The size cap covers PLAIN bodies too — you can't sidestep the bomb guard by not compressing."""
    from peakstone.api.main import _XzBody
    monkeypatch.setattr(_XzBody, "MAX_DECOMPRESSED", 2000)   # shrink the cap so the test stays small
    r = client.post("/submissions", content=b'{"x":"' + b"a" * 5000 + b'"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 413

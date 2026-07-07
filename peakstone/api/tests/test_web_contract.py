"""The web client's hand-written TS types vs what the API actually emits (review R25).

The Next.js site blind-casts API JSON into the types in web/lib/api.ts; nothing validated them, so
the backend had drifted ~8 fields ahead. The API's endpoints return plain dicts (no response_model
— adding one would silently FILTER unknown keys out of live responses), so the contract is pinned
here instead: every key each endpoint emits must be declared on the corresponding TS type. A new
backend field fails this test until web/lib/api.ts declares it. One-way on purpose — the TS side
may declare optional fields the API omits for a given row.

Skips when web/lib/api.ts isn't present (installed package, not the repo checkout).
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_DB = os.path.join(tempfile.mkdtemp(), "test-web-contract.db")
os.environ.setdefault("PEAKSTONE_DATABASE_URL", f"sqlite:///{_DB}")
os.environ["PEAKSTONE_SKIP_FILE_HASH"] = "1"
os.environ.setdefault("PEAKSTONE_GITHUB_CLIENT_ID", "test_cid")
os.environ.setdefault("PEAKSTONE_GITHUB_CLIENT_SECRET", "test_sec")

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from peakstone.engine import bundle, keys
from peakstone.api.main import app

API_TS = Path(__file__).parents[3] / "web" / "lib" / "api.ts"

pytestmark = pytest.mark.skipif(not API_TS.exists(), reason="web/lib/api.ts not in this checkout")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _ts_types() -> dict[str, set[str]]:
    """{type name: declared field names} for every `export type X = {...}` in web/lib/api.ts.
    Top-level fields are the 2-space-indented `name:` / `name?:` lines; inline object literals in
    a field's value (e.g. `engine: { name?: ... }`) belong to that field and are not fields."""
    out: dict[str, set[str]] = {}
    current: str | None = None
    for line in API_TS.read_text().splitlines():
        one = re.match(r"export type (\w+)\s*=\s*\{(.+)\};", line)   # one-liner types
        if one:
            out[one.group(1)] = set(re.findall(r"(\w+)\??:", one.group(2)))
            continue
        m = re.match(r"export type (\w+)\s*=\s*\{", line)
        if m:
            current = m.group(1)
            out[current] = set()
            continue
        if current:
            if line.startswith("};"):
                current = None
                continue
            f = re.match(r"  (\w+)\??:", line)
            if f:
                out[current].add(f.group(1))
    return out


def _mk_bundle():
    priv = Ed25519PrivateKey.generate()
    pub = keys.public_key_b64(priv)
    rows = [{"model": "contract-m", "challenge": f"contract-c{i}", "type": "architecture",
             "difficulty": 3, "scoring": "tests", "final_score": 1.0, "passed": 10, "total": 10,
             "response": "solution text", "stdout": "ok", "stderr": ""}
            for i in range(2)]
    b = bundle.produce_bundle(
        {"models": ["contract-m"], "judge": None, "timestamp": "webcontract",
         "gpu": {"name": "RTX 4090", "driver_version": "595"}}, rows, sign=False)
    b["environment"]["vram_gb"] = 24
    bundle.sign_inplace(b, priv, pub)
    return b


def _assert_declared(emitted: dict, ts: dict[str, set[str]], type_name: str, where: str):
    extra = set(emitted) - ts[type_name]
    assert not extra, (f"{where} emits {sorted(extra)} not declared on web/lib/api.ts type "
                       f"{type_name} — add the field(s) there (review R25)")


def test_endpoints_match_web_types(client):
    ts = _ts_types()
    r = client.post("/submissions", json=_mk_bundle())
    assert r.status_code == 201, r.text
    bundle_hash = r.json()["bundle_hash"]

    lb = client.get("/leaderboard").json()
    _assert_declared(lb, ts, "Leaderboard", "/leaderboard")
    row = next(x for x in lb["leaderboard"] if x["family"] == "contract-m")
    _assert_declared(row, ts, "LeaderRow", "/leaderboard row")
    _assert_declared(row["run"], ts, "Run", "/leaderboard row.run")
    _assert_declared(row["held_out"], ts, "HeldOut", "/leaderboard row.held_out")

    mp = client.get("/models/contract-m").json()
    _assert_declared(mp, ts, "ModelPage", "/models/{family}")
    # ModelRun = LeaderRow minus rank/family/release_date, plus suite
    model_run_fields = (ts["LeaderRow"] - {"rank", "family", "release_date"}) | {"suite"}
    extra = set(mp["runs"][0]) - model_run_fields
    assert not extra, f"/models runs[] emits {sorted(extra)} not declared on ModelRun (R25)"

    rr = client.get(f"/runs/{bundle_hash}").json()
    _assert_declared(rr, ts, "RunResults", "/runs/{hash}")
    _assert_declared(rr["results"][0], ts, "RunChallengeRow", "/runs/{hash} results[]")

    rc = client.get(f"/runs/{bundle_hash}/challenge/contract-c0").json()
    _assert_declared(rc, ts, "RunChallenge", "/runs/{hash}/challenge/{id}")
    if rc.get("transcript"):
        _assert_declared(rc["transcript"], ts, "Transcript", "…/challenge/{id} transcript")

    cl = client.get("/challenges").json()
    _assert_declared(cl, ts, "ChallengeList", "/challenges")
    _assert_declared(cl["challenges"][0], ts, "ChallengeRow", "/challenges rows")

    cd = client.get("/challenges/contract-c0").json()
    _assert_declared(cd, ts, "ChallengeDetail", "/challenges/{id}")
    if cd["results"]:   # per-challenge boards are trust-gated (R6); a self-reported row won't show
        _assert_declared(cd["results"][0], ts, "ChallengeResult", "/challenges/{id} results[]")
        _assert_declared(cd["results"][0]["run"], ts, "Run", "/challenges/{id} results[].run")

    _assert_declared(client.get("/facets").json(), ts, "Facets", "/facets")

    pl = client.get("/proposals?status=all").json()
    _assert_declared(pl, ts, "ProposalList", "/proposals")

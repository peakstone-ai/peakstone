"""Commit-and-reveal slice 3: sealed ingest, no-credit-until-reveal, the /reveals flow."""
from __future__ import annotations

import os
import tempfile

_DB = os.path.join(tempfile.mkdtemp(), "test-reveal.db")
os.environ["PEAKSTONE_DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["PEAKSTONE_SKIP_FILE_HASH"] = "1"

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from peakstone.engine import bundle, keys
from peakstone.engine import private as eng_private
from peakstone.api.main import app

SALT = "ab" * 32


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _newkey():
    p = Ed25519PrivateKey.generate()
    return p, keys.public_key_b64(p)


def _files(cid="priv-rev-01"):
    """A revealable challenge payload: the exact {relpath: text} map a reveal ships."""
    return {
        "meta.toml": f'id = "{cid}"\ntitle = "private probe"\nlanguage = "python"\n'
                     'difficulty = 3\ncategory = "basic"\nscoring = "tests"\n'
                     'solution_file = "solution.py"\n',
        "spec.md": "# secret spec\n",
        "tests/test_x.py": "def test_x():\n    assert True\n",
        "reference/solution.py": "x = 1\n",
    }


def _pub_row(cid, f):
    return {"model": "m", "challenge": cid, "type": "architecture", "difficulty": 4,
            "scoring": "tests", "final_score": f, "passed": int(f * 10), "total": 10,
            "tok_per_s": 50, "latency_s": 2.0, "response": "x", "stdout": "ok"}


def _priv_result(commitment, cid="priv-rev-01", f=1.0):
    """A bundle-shaped SEALED row (what engine.bundle emits for a private challenge)."""
    return {"challenge_id": cid, "challenge_hash": "(private)", "private": True,
            "commitment": commitment, "verification": "deterministic-tests",
            "category": "basic", "difficulty": 3,
            "score": {"final": f, "passed": int(f * 10), "total": 10}}


def _submit(client, priv, pub, *, publics=(0.5, 0.5), private_rows=(), model="m",
            suite_ts="20260704-000000", vram=24):
    b = bundle.produce_bundle(
        {"models": [model], "judge": None, "timestamp": suite_ts,
         "gpu": {"name": "RTX 4090", "driver_version": "595"}},
        [_pub_row(f"arch-{i}", f) for i, f in enumerate(publics)], sign=False)
    b["results"] += list(private_rows)
    b["environment"]["vram_gb"] = vram
    bundle.sign_inplace(b, priv, pub)
    return client.post("/submissions", json=b)


def _run(client, model="m"):
    rows = client.get(f"/models/{model}").json()["runs"]
    return rows[0]


COM = None  # the sealed commitment shared across the module's flow tests


def test_sealed_ingest_no_credit(client):
    global COM
    COM = eng_private.commitment_from_files(_files(), SALT)
    priv, pub = _newkey()
    r = _submit(client, priv, pub, publics=(0.5, 0.5), private_rows=[_priv_result(COM, f=1.0)])
    assert r.status_code == 201, r.text
    run = _run(client)
    assert run["n_committed"] == 1 and run["n_revealed"] == 0
    assert run["code_score"] == 0.5          # the sealed 1.0 must NOT lift the axis
    assert run["n_total"] == 2               # coverage counts only what's open
    ids = {c["id"] for c in client.get("/challenges").json()["challenges"]}
    assert "priv-rev-01" not in ids          # sealed slug never registers in the corpus


def test_reveal_wrong_salt_is_404(client):
    r = client.post("/reveals", json={"salt": "cd" * 32, "files": _files()})
    assert r.status_code == 404


def test_reveal_malformed(client):
    assert client.post("/reveals", json={"salt": "not-hex", "files": _files()}).status_code == 400
    assert client.post("/reveals", json={"salt": SALT, "files": {}}).status_code == 400


def test_reveal_flow_unlocks_results(client):
    r = client.post("/reveals", json={"salt": SALT, "files": _files(),
                                      "validation": {"reference_passes": True}})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["challenge_id"] == "priv-rev-01" and out["n_results_revealed"] == 1
    assert out["commitment"] == COM and out["published_at"]

    run = _run(client)
    assert run["n_revealed"] == 1
    assert run["code_score"] == round((0.5 + 0.5 + 1.0) / 3, 3)   # the revealed 1.0 now counts
    ch = {c["id"]: c for c in client.get("/challenges").json()["challenges"]}["priv-rev-01"]
    assert ch["n_runs"] == 1 and ch["pass_rate"] == 1.0            # joined the corpus with stats


def test_reveal_twice_is_409(client):
    r = client.post("/reveals", json={"salt": SALT, "files": _files()})
    assert r.status_code == 409 and "priv-rev-01" in r.text


def test_late_committer_auto_reveals(client):
    """A sealed row submitted AFTER its commitment was opened counts immediately."""
    priv, pub = _newkey()
    r = _submit(client, priv, pub, publics=(0.0,), private_rows=[_priv_result(COM, f=1.0)],
                model="late", suite_ts="20260704-000001", vram=16)
    assert r.status_code == 201, r.text
    run = _run(client, "late")
    assert run["n_committed"] == 1 and run["n_revealed"] == 1
    assert run["code_score"] == 0.5           # (0.0 + 1.0) / 2 — revealed row counts at once


def test_reveal_id_collision_is_409(client):
    files = _files(cid="arch-0")              # collides with a lazily-registered public id
    salt2 = "ee" * 32
    priv, pub = _newkey()
    com = eng_private.commitment_from_files(files, salt2)
    _submit(client, priv, pub, publics=(0.1,), private_rows=[_priv_result(com, cid="arch-0")],
            model="clash", suite_ts="20260704-000002", vram=8)
    r = client.post("/reveals", json={"salt": salt2, "files": files})
    assert r.status_code == 409 and "already exists" in r.text


def test_private_rows_never_pollute_public_challenge_stats(client):
    detail = client.get("/challenges/arch-0").json()
    best = {row["family"]: row["score"] for row in detail["results"]}
    assert best["clash"] == 0.1               # its PUBLIC arch-0 row shows; the sealed 1.0 does not


def test_ingest_rejects_malformed_private_rows(client):
    priv, pub = _newkey()
    bad = _priv_result(COM); del bad["commitment"]; bad["private"] = True
    r = _submit(client, priv, pub, publics=(0.1,), private_rows=[bad],
                model="bad1", suite_ts="20260704-000003", vram=4)
    assert r.status_code == 400 and "commitment" in r.text
    leaky = _priv_result(COM); leaky["transcript"] = {"raw_output": "SECRET"}
    r = _submit(client, priv, pub, publics=(0.1,), private_rows=[leaky],
                model="bad2", suite_ts="20260704-000004", vram=4)
    assert r.status_code == 400 and "transcript" in r.text


def test_repro_sig_ignores_private_rows(client):
    """Two submitters with identical PUBLIC results but different private sets must still land in
    the same reproduction group (community verification of the public part)."""
    from peakstone.api.ingest import _repro_sig
    pubs = [{"challenge_id": "a", "verification": "deterministic-tests", "score": {"final": 1.0}}]
    s1 = _repro_sig(pubs + [{"challenge_id": "p1", "private": True,
                             "verification": "deterministic-tests", "score": {"final": 0.0}}])
    s2 = _repro_sig(pubs + [{"challenge_id": "p2", "private": True,
                             "verification": "deterministic-tests", "score": {"final": 1.0}}])
    assert s1 == s2 == _repro_sig(pubs)

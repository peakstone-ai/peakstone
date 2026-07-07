"""`peakstone reproduce <hash>` — the verify-a-run verb (PLAN §12 D). Real crypto + a real tmp
corpus; the serve/bench/download externals are stubbed via the module's injection points (the
same convention as the existing reproduce() tests)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from peakstone.engine import bundle as eng_bundle
from peakstone.engine import keys
from peakstone.dashboard import reproduce as R


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """A two-challenge corpus the plan can hash, wired in as THE challenges dir."""
    for cid in ("rv-c0", "rv-c1"):
        d = tmp_path / "corpus" / "fam" / cid
        (d / "tests").mkdir(parents=True)
        (d / "meta.toml").write_text(f'id = "{cid}"\n')
        (d / "spec.md").write_text(f"spec {cid}")
    from peakstone.engine import paths
    monkeypatch.setattr(paths, "challenges_dir", lambda: tmp_path / "corpus")
    monkeypatch.setenv("PEAKSTONE_SKIP_FILE_HASH", "1")
    return tmp_path / "corpus"


def _original(corpus, finals=(1.0, 0.5)):
    """A signed 'published' bundle: built by the real producer (so it's schema-valid and carries
    the REAL corpus content hashes), then given a concrete model identity and re-signed — the
    same post-build-mutate-resign convention the ingest tests use."""
    rows = [{"model": "rv-fam", "challenge": cid, "type": "basic", "difficulty": 2,
             "scoring": "tests", "final_score": f, "passed": int(f * 10), "total": 10,
             "response": "sol", "stdout": ""}
            for cid, f in zip(("rv-c0", "rv-c1"), finals)]
    b = eng_bundle.produce_bundle(
        {"models": ["rv-fam"], "judge": None, "timestamp": "orig",
         "suite_id": "level-standard", "suite_version": "2026.08",
         "max_tokens": 4096, "gpu": None}, rows, sign=False)
    b["model"].update(artifact="Q4_K_M", hf_repo="org/rv", context=8192,
                      serve_flags="--reasoning-budget 0")
    priv = Ed25519PrivateKey.generate()
    eng_bundle.sign_inplace(b, priv, keys.public_key_b64(priv))
    return b


def _entry(present=True):
    return SimpleNamespace(name="rv-fam", repo="org/rv", file="models/rv/q4.gguf" if present else None,
                           port=9999, quant="Q4_K_M", present=present, ctx=8192)


def _stub_bench(results_by_id):
    """A bench stub that writes the results.json the real runner would."""
    def bench(name, ids, *, out_dir, log, ctx=None, reasoning=None, max_tokens=None):
        rows = [{"model": name, "challenge": cid, "type": "basic", "difficulty": 2,
                 "scoring": "tests", "final_score": results_by_id[cid],
                 "passed": int(results_by_id[cid] * 10), "total": 10,
                 "response": "sol", "stdout": ""} for cid in ids]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "results.json").write_text(json.dumps(
            {"meta": {"models": [name], "timestamp": "rv", "judge": None,
                      "max_tokens": max_tokens, "gpu": None},
             "results": rows}))
        return {}
    return bench


def _run(original, corpus, tmp_path, results_by_id, argv=None, *, monkeypatch=None, submits=None):
    logs: list[str] = []
    fit = SimpleNamespace(fits_now=True, fits_after_free=True, need_gb=1, free_gb=24, freeable_gb=0)
    monkeypatch.setattr(R.preflight, "check", lambda e: fit)
    if submits is not None:
        from peakstone.dashboard import client
        monkeypatch.setattr(client, "submit_bundle",
                            lambda api, b, **k: (submits.append(b), (201, "created"))[1])
    rc = R.reproduce_main(
        (argv or []) + [original["bundle_hash"], "--out", str(tmp_path / "out")],
        _fetch=lambda h: {"bundle": original, "trust_tier": "runner-verified", "reproductions": 0},
        _serve=lambda name, ctx=None, reasoning=None: SimpleNamespace(),
        _wait=lambda port, proc=None: True,
        _bench=_stub_bench(results_by_id),
        _stop=lambda p: None,
        _resolve=lambda plan, log: _entry(),
        log=logs.append)
    return rc, logs


def test_match_verdict_and_submit(tmp_path, corpus, monkeypatch):
    original = _original(corpus)                                    # rv-c0=1.0, rv-c1=0.5
    submits: list = []
    rc, logs = _run(original, corpus, tmp_path, {"rv-c0": 1.0, "rv-c1": 0.5},
                    argv=["--submit"], monkeypatch=monkeypatch, submits=submits)
    assert rc == 0
    assert any("MATCH" in l for l in logs)
    assert len(submits) == 1
    mine = submits[0]
    # the reproduction bundle restamps the ORIGINAL's suite identity — the server's group key
    assert mine["suite"]["id"] == "level-standard" and mine["suite"]["version"] == "2026.08"
    from peakstone.engine import repro
    assert repro.repro_sig(mine["results"]) == repro.repro_sig(original["results"])
    assert repro.verify_bundle(mine) == []                          # ours is signed + addressable


def test_mismatch_lists_flips_and_exits_1(tmp_path, corpus, monkeypatch):
    original = _original(corpus)
    rc, logs = _run(original, corpus, tmp_path, {"rv-c0": 0.0, "rv-c1": 0.1},
                    monkeypatch=monkeypatch)
    assert rc == 1
    assert any("MISMATCH" in l for l in logs)
    assert any("rv-c0" in l and "1.0" in l for l in logs)           # per-challenge flip list


def test_tampered_bundle_refused_before_running(tmp_path, corpus, monkeypatch):
    original = _original(corpus)
    original["results"][0]["score"]["final"] = 0.123                # tamper after signing
    ran: list = []
    rc = R.reproduce_main(
        [original["bundle_hash"]],
        _fetch=lambda h: {"bundle": original},
        _bench=lambda *a, **k: ran.append(1),
        log=lambda s: None)
    assert rc == 2 and not ran


def test_corpus_drift_refused(tmp_path, corpus, monkeypatch):
    original = _original(corpus)
    (corpus / "fam" / "rv-c0" / "spec.md").write_text("DRIFTED")    # local content changed
    logs: list = []
    rc = R.reproduce_main(
        [original["bundle_hash"]],
        _fetch=lambda h: {"bundle": original},
        log=logs.append)
    assert rc == 2
    assert any("corpus sync" in l for l in logs)


def test_quant_mismatch_refused(tmp_path, corpus, monkeypatch):
    original = _original(corpus)
    wrong = SimpleNamespace(name="rv-fam", repo="org/rv", quant="Q5_K_M", present=True,
                            port=9999, ctx=8192)
    logs: list = []
    rc = R.reproduce_main(
        [original["bundle_hash"]],
        _fetch=lambda h: {"bundle": original},
        _resolve=lambda plan, log: wrong,
        log=logs.append)
    assert rc == 2
    assert any("quant mismatch" in l for l in logs)

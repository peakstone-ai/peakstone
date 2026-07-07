"""engine.repro — the reproduce verb's core: deterministic vector (shared with ingest's
community-verification fingerprint), client-side bundle trust chain, plan, verdict."""
from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from peakstone.engine import bundle as eng_bundle
from peakstone.engine import keys, repro


def _row(cid, final=1.0, *, chash="h", verification="deterministic-tests", private=False):
    r = {"challenge_id": cid, "challenge_hash": chash, "verification": verification,
         "score": {"final": final, "passed": int(final * 10), "total": 10}}
    if private:
        r["private"] = True
        r["commitment"] = "c" * 64
    return r


# --- the vector ---------------------------------------------------------------------------------

def test_det_vector_excludes_judge_env_and_private_rows():
    rows = [_row("a"), _row("b", verification="llm-judge"),
            _row("c", verification="goal-state-env"), _row("d", private=True)]
    assert [v[0] for v in repro.det_vector(rows)] == ["a"]


def test_repro_sig_matches_ingest_fingerprint():
    """The server groups reproductions by ingest._repro_sig; the client's MATCH is repro.repro_sig.
    They must be the same function — a drift here would let a client-verified MATCH fail to
    promote (or vice versa)."""
    from peakstone.api import ingest
    rows = [_row("a", 0.5), _row("b", 1.0, chash="h2"), _row("j", verification="llm-judge")]
    assert ingest._repro_sig(rows) == repro.repro_sig(rows) is not None
    assert ingest._repro_sig([]) is None and repro.repro_sig([]) is None


def test_repro_sig_rounds_float_noise_but_not_content():
    base = [_row("a", 0.51234449)]
    assert repro.repro_sig(base) == repro.repro_sig([_row("a", 0.51235)])  # rounds to 4 dp
    assert repro.repro_sig(base) != repro.repro_sig([_row("a", 0.51234449, chash="other")])


# --- the trust chain ----------------------------------------------------------------------------

def _signed_bundle():
    priv = Ed25519PrivateKey.generate()
    pub = keys.public_key_b64(priv)
    b = eng_bundle.produce_bundle(
        {"models": ["repro-m"], "judge": None, "timestamp": "t",
         "gpu": {"name": "g", "driver_version": "1"}},
        [{"model": "repro-m", "challenge": "c1", "type": "basic", "difficulty": 1,
          "scoring": "tests", "final_score": 1.0, "passed": 10, "total": 10,
          "response": "x", "stdout": ""}], sign=False)
    eng_bundle.sign_inplace(b, priv, pub)
    return b


def test_verify_bundle_accepts_intact_and_catches_tampering():
    b = _signed_bundle()
    assert repro.verify_bundle(b) == []
    tampered = json.loads(json.dumps(b))
    tampered["results"][0]["score"]["final"] = 0.0   # tamper post-signature
    problems = repro.verify_bundle(tampered)
    assert any("content-address" in p for p in problems)
    unsigned = json.loads(json.dumps(b))
    del unsigned["submitter"]["signature"]
    assert any("signature" in p for p in repro.verify_bundle(unsigned))


# --- the plan -----------------------------------------------------------------------------------

def test_plan_pins_ids_and_flags_corpus_drift(tmp_path):
    (tmp_path / "fam" / "c1" / "tests").mkdir(parents=True)
    (tmp_path / "fam" / "c1" / "meta.toml").write_text('id = "c1"\n')
    (tmp_path / "fam" / "c1" / "spec.md").write_text("spec")
    local_hash = eng_bundle.challenge_hashes(tmp_path)["c1"]
    b = {"suite": {"id": "level-standard", "version": "2026.08"},
         "model": {"family": "m", "artifact": "Q4_K_M", "hf_repo": "org/repo",
                   "file_sha256": "abc", "context": 32768,
                   "serve_flags": "--reasoning-budget 0",
                   "sampling": {"max_tokens": 8192}},
         "results": [_row("c1", chash=local_hash), _row("c2", chash="nope"),
                     _row("j1", verification="llm-judge")]}
    p = repro.plan(b, tmp_path)
    assert p.ids == ["c1", "c2"]                       # judge row excluded from the vector
    assert p.missing == ["c2"] and p.hash_mismatches == []
    assert not p.ready
    assert (p.suite_id, p.suite_version) == ("level-standard", "2026.08")
    assert p.max_tokens == 8192 and p.context == 32768 and p.reasoning_budget == 0
    # same corpus but drifted content → mismatch flagged
    (tmp_path / "fam" / "c1" / "spec.md").write_text("CHANGED")
    b2 = {**b, "results": [_row("c1", chash=local_hash)]}
    p2 = repro.plan(b2, tmp_path)
    assert p2.hash_mismatches == ["c1"] and not p2.ready


# --- the verdict --------------------------------------------------------------------------------

def test_verdict_match_iff_vectors_identical():
    orig = [_row("a", 1.0), _row("b", 0.5)]
    same = [_row("b", 0.5), _row("a", 1.0)]           # order-independent
    assert repro.verdict(orig, same).status == "MATCH"
    assert repro.repro_sig(orig) == repro.repro_sig(same)


def test_verdict_compatible_and_mismatch_thresholds():
    orig = [_row(f"c{i}", 1.0) for i in range(100)]
    one_flip = [_row(f"c{i}", 1.0 if i else 0.0) for i in range(100)]
    v = repro.verdict(orig, one_flip)
    assert v.status == "COMPATIBLE" and len(v.flips) == 1
    assert v.flips[0]["challenge"] == "c0" and v.flips[0]["yours"] == 0.0
    many = [_row(f"c{i}", 1.0 if i > 4 else 0.0) for i in range(100)]
    assert repro.verdict(orig, many).status == "MISMATCH"


def test_verdict_missing_and_extra_rows_are_flips():
    orig = [_row("a"), _row("b")]
    v = repro.verdict(orig, [_row("a")])
    assert v.status != "MATCH"
    assert any(f["challenge"] == "b" and f["yours"] == "(absent)" for f in v.flips)
    v2 = repro.verdict([_row("a")], [_row("a"), _row("x")])
    assert any(f["challenge"] == "x" and f["original"] == "(absent)" for f in v2.flips)


def test_verdict_never_promotes_compatible():
    """COMPATIBLE is informative only: the sigs differ, so the server would not group them —
    the client verdict must agree that only MATCH means verified."""
    orig, near = [_row("a"), _row("b")], [_row("a"), _row("b", 0.9)]
    v = repro.verdict(orig, near)
    assert v.status == "COMPATIBLE" and not v.ok
    assert repro.repro_sig(orig) != repro.repro_sig(near)

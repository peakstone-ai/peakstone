"""Regression tests for the bundle/sandbox hardening (deferred audit items 1-4)."""
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from peakstone.engine import bundle, keys, sandbox


def test_nominal_ram_gib():
    from peakstone.engine.bundle import _nominal_ram_gib
    assert _nominal_ram_gib(67_032_477_696) == 64        # 64 GiB machine (MemTotal 62.4 GiB) -> 64, not 67
    assert _nominal_ram_gib(33_000_000_000) == 32        # ~30.7 GiB usable -> 32
    assert _nominal_ram_gib(16 * 2**30) == 16
    assert _nominal_ram_gib(8 * 2**30 - 400 * 2**20) == 8  # just under 8 GiB -> 8


def test_bundle_carries_error_type():
    b = bundle.produce_bundle(
        {"models": ["m"], "judge": None, "timestamp": "t", "gpu": {"name": "x"}},
        [{"challenge": "c", "type": "architecture", "final_score": 0.0,
          "error": "repetition-loop", "response": "loop loop loop"}], sign=False)
    assert b["results"][0]["transcript"]["error"] == "repetition-loop"


def test_capture_env_records_model_footprint():
    env = bundle.capture_env({"name": "RTX 4090"}, {"vram_mib": 24576, "ram_mib": 26624})
    assert env["vram_used_gb"] == 24.0 and env["ram_used_gb"] == 26.0   # measured model footprint
    assert "vram_used_gb" not in bundle.capture_env({"name": "x"})      # old bundles: no used keys


def test_effective_sandbox_records_truth():
    # config may ask for 'docker' but the test runner only implements subprocess -> record the truth
    assert sandbox.effective_sandbox("docker") == "subprocess"
    assert sandbox.effective_sandbox(None) == "subprocess"
    assert sandbox.effective_sandbox("subprocess") == "subprocess"


def test_file_sha256_verified_flag(monkeypatch):
    monkeypatch.setenv("PEAKSTONE_SKIP_FILE_HASH", "1")
    assert bundle._model_file_hash(Path("/nope.gguf")) == ("(skipped)", False)
    monkeypatch.delenv("PEAKSTONE_SKIP_FILE_HASH")
    assert bundle._model_file_hash(Path("/nope.gguf")) == ("(missing)", False)


def _bundle(sign=False, **kw):
    return bundle.produce_bundle(
        {"models": ["m"], "judge": None, "timestamp": "t", "gpu": {"name": "x", "driver_version": "1"}},
        [{"model": "m", "challenge": "c", "type": "data", "difficulty": 2, "scoring": "tests",
          "final_score": 1.0, "passed": 1, "total": 1, "response": "x", "stdout": "ok"}], sign=sign, **kw)


def test_pubkey_is_bound_into_the_hash():
    p = Ed25519PrivateKey.generate()
    pub = keys.public_key_b64(p)
    b = bundle.sign_inplace(_bundle(), p, pub)
    # the legit bundle re-hashes to its claimed hash
    assert bundle._sha256_bytes(bundle.canonical_bytes(bundle._without_sig(b))) == b["bundle_hash"]
    # swapping the submitter pubkey now changes the content-address (it's inside the hash)
    b["submitter"]["pubkey"] = "ATTACKER-KEY"
    assert bundle._sha256_bytes(bundle.canonical_bytes(bundle._without_sig(b))) != b["bundle_hash"]
    # but only the signature is excluded — re-signing without touching anything else is stable
    b2 = bundle.sign_inplace(_bundle(), p, pub)
    h = b2["bundle_hash"]
    b2["submitter"]["signature"] = "different"
    assert bundle._sha256_bytes(bundle.canonical_bytes(bundle._without_sig(b2))) == h

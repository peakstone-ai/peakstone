"""Commit-and-reveal slices 1–2: the commitment crypto core + the redacted private bundle row."""
from __future__ import annotations

import json
from pathlib import Path

from peakstone.engine import private
from peakstone.engine.bundle import _result

SALT_A = "aa" * 32
SALT_B = "bb" * 32


def _mk_challenge(root: Path, cid="priv-01", private=True) -> Path:
    d = root / ("private" if private else "public") / cid
    (d / "tests").mkdir(parents=True)
    (d / "reference").mkdir()
    (d / "meta.toml").write_text(f'id = "{cid}"\ntitle = "t"\nlanguage = "python"\n'
                                 'difficulty = 2\ncategory = "basic"\nscoring = "tests"\n'
                                 'solution_file = "solution.py"\n')
    (d / "spec.md").write_text("# secret spec\n")
    (d / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    (d / "reference" / "solution.py").write_text("x = 1\n")
    return d


# ---------------------------------------------------------------- crypto core (slice 2)

def test_commitment_deterministic_and_salt_sensitive(tmp_path):
    d = _mk_challenge(tmp_path)
    c1 = private.commitment(d, salt=SALT_A)
    assert c1.startswith("sha256:") and c1 == private.commitment(d, salt=SALT_A)
    assert private.commitment(d, salt=SALT_B) != c1          # salt binds
    (d / "spec.md").write_text("# secret spec v2\n")
    assert private.commitment(d, salt=SALT_A) != c1          # content binds


def test_salt_file_created_persisted_and_excluded_from_hash(tmp_path):
    d = _mk_challenge(tmp_path)
    salt = private.ensure_salt(d)
    assert (d / private.SALT_FILE).is_file() and private.ensure_salt(d) == salt
    # the salt file (a dot-file) must not hash itself in — same commitment with or without it
    c_with = private.commitment(d, salt=SALT_A)
    (d / private.SALT_FILE).unlink()
    assert private.commitment(d, salt=SALT_A) == c_with


def test_verify_reveal_roundtrip_and_tamper(tmp_path):
    d = _mk_challenge(tmp_path)
    c = private.commitment(d, salt=SALT_A)
    assert private.verify_reveal(d, SALT_A, c)
    assert not private.verify_reveal(d, SALT_B, c)            # wrong salt
    (d / "tests" / "test_x.py").write_text("def test_x():\n    assert False\n")
    assert not private.verify_reveal(d, SALT_A, c)            # tampered content
    assert not private.verify_reveal(d, "not-hex", c)         # malformed salt -> False, not a crash


def test_is_private_and_corpus_scan(tmp_path):
    dp = _mk_challenge(tmp_path, "priv-01", private=True)
    du = _mk_challenge(tmp_path, "pub-01", private=False)
    assert private.is_private_dir(dp) and not private.is_private_dir(du)
    m = private.private_commitments(tmp_path)
    assert set(m) == {"priv-01"} and m["priv-01"].startswith("sha256:")
    assert (dp / private.SALT_FILE).is_file()                 # salt auto-created by the scan


def test_gate_reveal_is_reference_must_pass(tmp_path):
    import shutil
    import pytest
    from peakstone.engine.propose import ProposalError
    d = _mk_challenge(tmp_path)
    shutil.rmtree(d / "reference")                             # break the structure (no reference)
    with pytest.raises(ProposalError):
        private.gate_reveal(d)


# ---------------------------------------------------------------- bundle shape (slice 1)

_ROW = {
    "model": "m", "challenge": "priv-01", "language": "python", "difficulty": 2,
    "category": "basic", "type": "basic", "scoring": "tests", "final_score": 1.0,
    "passed": 3, "total": 3, "tok_per_s": 50.0, "latency_s": 1.2,
    "response": "SECRET SOLUTION", "stdout": "SECRET OUTPUT", "system_prompt": "SECRET SPEC",
    "judge_detail": {"scores": {"style": 9}},
}


def test_private_row_is_redacted_and_pinned():
    cpriv = {"priv-01": "sha256:" + "ab" * 32}
    r = _result(dict(_ROW), {"priv-01": "realdirhash"}, "judge-model", cpriv=cpriv)
    assert r["private"] is True and r["commitment"] == cpriv["priv-01"]
    assert r["challenge_hash"] == "(private)"                  # never the real dir hash
    assert r["score"] == {"final": 1.0, "passed": 3, "total": 3}
    blob = json.dumps(r)
    assert "SECRET" not in blob and "transcript" not in r and "judge" not in r
    assert "published_at" not in r
    assert r["category"] == "basic" and r["tok_per_s"] == 50.0  # safe metadata kept


def test_public_row_unaffected():
    r = _result(dict(_ROW, challenge="pub-01"), {"pub-01": "dirhash"}, None, cpriv={"priv-01": "x"})
    assert r["challenge_hash"] == "dirhash" and "private" not in r and "commitment" not in r
    assert r["transcript"]["raw_output"] == "SECRET SOLUTION"  # public rows keep transcripts


def test_private_row_validates_against_schema():
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[1]
                         / "schema" / "result-bundle.schema.json").read_text())
    r = _result(dict(_ROW), {}, None, cpriv={"priv-01": "sha256:" + "cd" * 32})
    jsonschema.validate(r, {"$defs": schema["$defs"], "$ref": "#/$defs/result"})

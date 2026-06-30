"""Sandbox path containment: untrusted model output must not write/read outside the workdir (review M1)."""
import pytest

from peakstone.engine import sandbox


def test_write_solution_writes_normal_files(tmp_path):
    sandbox._write_solution(tmp_path, {"sol.py": "print(1)", "pkg/mod.py": "x"})
    assert (tmp_path / "sol.py").read_text() == "print(1)"
    assert (tmp_path / "pkg" / "mod.py").read_text() == "x"


def test_write_solution_rejects_parent_traversal(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    with pytest.raises(ValueError, match="escapes the sandbox"):
        sandbox._write_solution(workdir, {"../../evil.txt": "pwned"})
    assert not (tmp_path / "evil.txt").exists()                  # nothing written outside


def test_write_solution_rejects_absolute_path(tmp_path):
    with pytest.raises(ValueError, match="escapes the sandbox"):
        sandbox._write_solution(tmp_path, {"/tmp/peakstone-escape-test": "pwned"})


def test_write_solution_rejects_embedded_traversal(tmp_path):
    # the lstrip('./')-style cleanup elsewhere misses this; the workdir-containment check catches it
    with pytest.raises(ValueError, match="escapes the sandbox"):
        sandbox._write_solution(tmp_path, {"foo/../../escape": "pwned"})


def test_agentic_read_file_traversal_contained(tmp_path):
    """The agentic read_file tool must not read host files via `tests/../../x` into the transcript."""
    from types import SimpleNamespace
    from peakstone.engine.agentic import Workspace
    chdir = tmp_path / "ch"
    chdir.mkdir()
    (tmp_path / "secret.txt").write_text("TOPSECRET")          # sits OUTSIDE the challenge dir
    ws = Workspace(SimpleNamespace(dir=chdir), {})
    r = ws.read_file("tests/../../secret.txt")
    assert "error" in r and "TOPSECRET" not in str(r)


def test_agentic_write_file_rejects_embedded_traversal(tmp_path):
    from types import SimpleNamespace
    from peakstone.engine.agentic import Workspace
    ws = Workspace(SimpleNamespace(dir=tmp_path), {})
    assert "error" in ws.write_file("foo/../../escape", "x")    # embedded traversal survives lstrip
    assert ws.write_file("sol.py", "ok").get("ok")              # a normal path still works


def test_redact_secrets_scrubs_signing_key(monkeypatch, tmp_path):
    """Generated code that reads + prints the signing key must not leak it into the transcript (M1)."""
    from peakstone.engine import keys, sandbox
    keyfile = tmp_path / "key.ed25519"
    keyfile.write_text("c2VjcmV0LXNpZ25pbmcta2V5LWJhc2U2NA==")     # stand-in b64 private key
    monkeypatch.setattr(keys, "KEY_PATH", keyfile)
    out = sandbox._redact_secrets("test ok\nleaked=c2VjcmV0LXNpZ25pbmcta2V5LWJhc2U2NA==\n")
    assert "c2VjcmV0" not in out and "[REDACTED-SECRET]" in out


def test_redact_secrets_scrubs_credential_env(monkeypatch):
    from peakstone.engine import sandbox
    monkeypatch.setenv("HF_TOKEN", "hf_supersecrettoken12345")
    assert "hf_supersecret" not in sandbox._redact_secrets("got HF_TOKEN=hf_supersecrettoken12345 here")

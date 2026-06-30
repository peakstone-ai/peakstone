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

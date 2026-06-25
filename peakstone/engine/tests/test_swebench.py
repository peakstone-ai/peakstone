"""SWE-bench repo-patch harness: pure parsing/check helpers + a docker-gated synthetic run."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from peakstone.engine import swebench as sb


def test_parse_pytest():
    out = ("PASSED tests/test_a.py::test_one\n"
           "FAILED tests/test_a.py::test_two\n"
           "ERROR tests/test_b.py::test_three\n"
           "SKIPPED tests/test_b.py::test_four\n"
           "some other noise\n")
    r = sb.parse_pytest(out)
    assert r == {"tests/test_a.py::test_one": "passed", "tests/test_a.py::test_two": "failed",
                 "tests/test_b.py::test_three": "error", "tests/test_b.py::test_four": "skipped"}


def test_patched_files():
    diff = ("diff --git a/pkg/mod.py b/pkg/mod.py\n--- a/pkg/mod.py\n+++ b/pkg/mod.py\n"
            "@@ -1 +1 @@\n-x\n+y\n"
            "diff --git a/new.py b/new.py\n--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+z\n")
    assert sb.patched_files(diff) == ["pkg/mod.py", "new.py"]


def test_extract_diff_from_fence_and_raw():
    fenced = "Sure, here is the fix:\n```diff\ndiff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n```\ndone"
    assert sb.extract_diff(fenced).startswith("diff --git a/m.py b/m.py")
    raw = "reasoning...\ndiff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert sb.extract_diff(raw).startswith("diff --git")
    assert sb.extract_diff("no patch here") == ""


def test_resolved():
    f2p = ["t::a", "t::b"]
    p2p = ["t::c"]
    assert sb.resolved({"t::a": "passed", "t::b": "passed", "t::c": "passed"}, f2p, p2p)
    assert not sb.resolved({"t::a": "passed", "t::b": "failed", "t::c": "passed"}, f2p, p2p)  # f2p fail
    assert not sb.resolved({"t::a": "passed", "t::b": "passed", "t::c": "failed"}, f2p, p2p)  # p2p regress
    assert not sb.resolved({}, [], p2p)                                                       # no f2p


import json


class _FakeAgentClient:
    """Scripted tool-calling model: turn 1 fixes the file, turn 2 calls done."""
    def __init__(self, write):
        self._write = write
        self.n = 0

    def chat_tools(self, model, msgs, tools, **kw):
        self.n += 1
        if self.n == 1:
            tc = {"id": "1", "function": {"name": "write_file", "arguments": json.dumps(self._write)}}
        else:
            tc = {"id": "2", "function": {"name": "done", "arguments": "{}"}}
        return {"message": {"role": "assistant", "tool_calls": [tc]}, "error": None}


class _FakeSandbox:
    def __init__(self):
        self.files = {}

    def exec(self, cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def read(self, path, **kw):
        return self.files.get(path, "stub contents")

    def write(self, path, content, **kw):
        self.files[path] = content
        return subprocess.CompletedProcess("write", 0, "", "")


def test_agent_loop_drives_tools_and_stops_on_done():
    fake = _FakeSandbox()
    client = _FakeAgentClient({"path": "mymod.py", "content": "def add(a, b):\n    return a + b\n"})
    inst = {"problem_statement": "add() is wrong"}
    transcript = sb._run_agent(fake, inst, client, "m", {}, max_turns=10, log=[])
    assert fake.files["mymod.py"].endswith("a + b\n")     # the agent's edit landed
    assert "write_file" in transcript and "done" in transcript
    assert client.n == 2                                # stopped right after done, didn't run all turns


def test_edit_file_dispatch():
    fake = _FakeSandbox()
    fake.files["m.py"] = "def f():\n    return 1\n"
    ok = sb._agent_dispatch(fake, "edit_file", {"path": "m.py", "old": "return 1", "new": "return 2"})
    assert ok.get("ok") and fake.files["m.py"] == "def f():\n    return 2\n"
    nf = sb._agent_dispatch(fake, "edit_file", {"path": "m.py", "old": "return 9", "new": "x"})
    assert "not found" in nf.get("error", "")
    fake.files["d.py"] = "a\na\n"
    amb = sb._agent_dispatch(fake, "edit_file", {"path": "d.py", "old": "a", "new": "b"})
    assert "matches" in amb.get("error", "")


class _ChatThenAct:
    """Replies with prose first (no tool call), then write_file, then done."""
    def __init__(self):
        self.n = 0

    def chat_tools(self, model, msgs, tools, **kw):
        self.n += 1
        if self.n == 1:
            return {"message": {"role": "assistant", "content": "I'll fix it by editing mymod.py."},
                    "error": None}
        if self.n == 2:
            tc = {"id": "1", "function": {"name": "write_file",
                  "arguments": json.dumps({"path": "m.py", "content": "fixed"})}}
            return {"message": {"role": "assistant", "tool_calls": [tc]}, "error": None}
        return {"message": {"role": "assistant",
                "tool_calls": [{"id": "2", "function": {"name": "done", "arguments": "{}"}}]}, "error": None}


def test_agent_nudges_on_prose_then_acts():
    fake = _FakeSandbox()
    client = _ChatThenAct()
    t = sb._run_agent(fake, {"problem_statement": "x"}, client, "m", {}, max_turns=6, log=[])
    assert "nudged" in t and fake.files.get("m.py") == "fixed"
    assert client.n == 3                          # nudged past the prose turn, then acted + done


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _docker_ok(), reason="docker not available")
def test_synthetic_reference_resolves():
    """Apply the gold patch to a fixtures-based instance and confirm the failing test passes."""
    inst = {
        "instance_id": "synthetic-add",
        "fixtures": {"mymod.py": "def add(a, b):\n    return a - b\n",
                     "test_mod.py": "from mymod import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
        "setup_cmds": ["pip install -q pytest"],
        "patch": ("diff --git a/mymod.py b/mymod.py\n--- a/mymod.py\n+++ b/mymod.py\n"
                  "@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"),
        "test_patch": "", "test_cmds": ["python -m pytest"],
        "FAIL_TO_PASS": ["test_mod.py::test_add"], "PASS_TO_PASS": [],
    }
    res = sb.run_repo_patch_task(inst, reference=True, timeout=600)
    assert res["resolved"] is True and res["final"] == 1.0, res.get("error") or res["transcript"][-500:]


@pytest.mark.skipif(not _docker_ok(), reason="docker not available")
def test_synthetic_agent_resolves():
    """The agent loop (scripted client) edits the live container repo and the failing test then passes."""
    inst = {
        "instance_id": "synthetic-add-agent",
        "fixtures": {"mymod.py": "def add(a, b):\n    return a - b\n",
                     "test_mod.py": "from mymod import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
        "setup_cmds": ["pip install -q pytest"],
        "test_patch": "", "test_cmds": ["python -m pytest"],
        "FAIL_TO_PASS": ["test_mod.py::test_add"], "PASS_TO_PASS": [],
    }
    client = _FakeAgentClient({"path": "mymod.py", "content": "def add(a, b):\n    return a + b\n"})
    res = sb.run_repo_patch_task(inst, client=client, model="m", run_cfg={}, agent=True, timeout=600)
    assert res["resolved"] is True and res["final"] == 1.0, res.get("error") or res["transcript"][-500:]

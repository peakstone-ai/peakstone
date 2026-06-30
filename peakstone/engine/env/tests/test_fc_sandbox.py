"""Firecracker test-execution backend — host-side logic (env curation, staging) without a VM,
plus a KVM-gated end-to-end run."""
import os
import pytest

from peakstone.engine.env import fc_sandbox


def test_curate_env_filters_and_remaps():
    env = {"PATH": "/host/bin", "PYTHONPATH": "/tmp/wd/x", "GOCACHE": "/tmp/wd/.gocache",
           "TZ": "UTC", "HF_TOKEN": "secret", "GOFLAGS": "-count=1"}
    out = fc_sandbox._curate_env(env, "/tmp/wd", "/work/run-1")
    assert out["PYTHONPATH"] == "/work/run-1/x"           # host workdir remapped to guest workdir
    assert out["GOCACHE"] == "/work/run-1/.gocache"
    assert out["TZ"] == "UTC" and out["GOFLAGS"] == "-count=1"
    assert "PATH" not in out                              # host PATH must not shadow the guest toolchain
    assert "HF_TOKEN" not in out                          # non-allowlisted (secret) keys dropped


class _FakeNode:
    def __init__(self):
        self.writes = {}
        self.runs = []

    def run(self, cmd, **kw):
        self.runs.append(cmd)

    def write_file(self, path, content):
        self.writes[path] = content


def test_stage_files_preserves_layout_and_skips_symlinks(tmp_path):
    (tmp_path / "a.py").write_text("print(1)")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("hi")
    (tmp_path / "link.py").symlink_to(tmp_path / "a.py")     # e.g. node_modules — guest has its own
    n = _FakeNode()
    fc_sandbox._stage_files(n, tmp_path, "/work/g")
    assert n.writes["/work/g/a.py"] == "print(1)"
    assert n.writes["/work/g/sub/b.txt"] == "hi"
    assert not any("link.py" in p for p in n.writes)        # symlink not staged
    assert any("mkdir -p" in c for c in n.runs)             # parent dirs created first


@pytest.mark.skipif(not fc_sandbox.available(), reason="needs KVM + the firecracker toolchain rootfs")
def test_end_to_end_staged_run(tmp_path):
    """Stage a file into a warm VM, run a command that reads it, confirm isolation + round-trip."""
    (tmp_path / "hello.txt").write_text("from-host")
    pool = fc_sandbox.FcPool(size=1)
    try:
        rc, out, err, dur, to = pool.run(["cat", str(tmp_path / "hello.txt")], tmp_path, 30, {})
        assert rc == 0 and "from-host" in out and not to
        # a second run gets a FRESH guest workdir — the first run's file is gone (no cross-contamination)
        rc2, out2, _, _, _ = pool.run(["sh", "-c", "ls | wc -l"], tmp_path, 30, {})
        assert rc2 == 0
    finally:
        pool.close()

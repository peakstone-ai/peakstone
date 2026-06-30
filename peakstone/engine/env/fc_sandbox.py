"""Warm Firecracker microVM pool as the test-execution backend (deep-M1 real isolation).

The per-language runners in engine/sandbox.py still lay out the solution + tests in a HOST workdir
(unchanged). This backend redirects only the *execution* step: it stages that workdir into a warm
microVM, runs the test command there (the guest has its own kernel + filesystem + uid — untrusted
code can't read the host's signing key or escape), and returns stdout/stderr/rc.

VMs boot once and are reused (boot ~1 s; warm vsock exec ~6 ms). Each run gets a fresh guest workdir
that is wiped afterward, so one challenge's files can never contaminate the next.

Activated by PEAKSTONE_SANDBOX=firecracker (engine/sandbox.py routes _run here). Requires KVM + the
toolchain rootfs (firecracker_agent/build-image.sh FC_TOOLCHAIN=1).
"""
from __future__ import annotations

import itertools
import os
import shlex
import threading
import time
from pathlib import Path

from .base import EnvSpec, NodeSpec
from .firecracker import FirecrackerProvider

# Env keys safe to forward from the host-built env into the guest. The guest's own PATH/GOROOT/etc.
# come from /etc/environment (seeded by the agent); we must NOT forward the host PATH or it would
# shadow the guest toolchain. Path-valued ones get the host workdir remapped to the guest workdir.
_FORWARD_ENV = ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "TZ",
                "GOCACHE", "GOPATH", "GOMODCACHE", "GOFLAGS", "GOPROXY", "GO111MODULE",
                "NODE_PATH", "NODE_OPTIONS")

_GUEST_ROOT = "/work"
_counter = itertools.count(1)


def _curate_env(env: dict, host_cwd: str, guest_dir: str) -> dict:
    """Keep only the runner-added keys that make sense in the guest, remapping host paths."""
    out = {}
    for k in _FORWARD_ENV:
        v = env.get(k)
        if v:
            out[k] = v.replace(host_cwd, guest_dir)
    return out


def _stage_files(node, host_dir: Path, guest_dir: str) -> None:
    """Copy every (text) file under host_dir into guest_dir, preserving relative layout. Symlinks
    (e.g. the host node_modules) are skipped — the guest image provides its own global toolchain."""
    files = [p for p in host_dir.rglob("*") if p.is_file() and not p.is_symlink()]
    dirs = sorted({str(Path(guest_dir) / p.relative_to(host_dir).parent) for p in files})
    if dirs:
        node.run("mkdir -p " + " ".join(shlex.quote(d) for d in dirs), timeout=20)
    for p in files:
        try:
            content = p.read_text()
        except (UnicodeDecodeError, OSError):
            continue   # binary/unreadable challenge asset — rare; tests are text
        node.write_file(str(Path(guest_dir) / p.relative_to(host_dir)), content)


class FcPool:
    """A pool of warm microVMs. Booted lazily (one per lease, up to `size`) and reused; lease() hands
    out a node, run-isolating each call in a fresh, wiped guest workdir."""

    def __init__(self, size: int = 1):
        self.size = max(1, size)
        self._envs: list = []
        self._free: list = []
        self._lock = threading.Lock()

    def _ensure_one(self):
        spec = EnvSpec(id=f"sandbox{len(self._envs)}", nodes=[NodeSpec(name="vm")])
        env = FirecrackerProvider().provision(spec)   # boots + waits for the agent
        self._envs.append(env)
        self._free.append(env.nodes["vm"])

    def _acquire(self):
        with self._lock:
            if not self._free and len(self._envs) < self.size:
                self._ensure_one()
            if self._free:
                return self._free.pop()
        # pool exhausted: serial callers won't hit this, but boot an extra rather than block
        with self._lock:
            self._ensure_one()
            return self._free.pop()

    def _release(self, node):
        with self._lock:
            self._free.append(node)

    def run(self, cmd: list[str], host_cwd: Path, timeout: int, env: dict) -> tuple:
        """Stage host_cwd into a warm VM, run cmd there, return (rc, out, err, dur, timed_out)."""
        host_cwd = host_cwd.resolve()
        guest_dir = f"{_GUEST_ROOT}/run-{os.getpid()}-{next(_counter)}"
        node = self._acquire()
        t0 = time.monotonic()
        try:
            node.run(f"rm -rf {shlex.quote(guest_dir)} && mkdir -p {shlex.quote(guest_dir)}", timeout=20)
            _stage_files(node, host_cwd, guest_dir)
            gcmd = [a.replace(str(host_cwd), guest_dir) for a in cmd]
            genv = _curate_env(env, str(host_cwd), guest_dir)
            line = f"cd {shlex.quote(guest_dir)} && exec {shlex.join(gcmd)}"
            r = node.run(line, timeout=timeout, _env=genv)
            dur = round(time.monotonic() - t0, 2)
            return (r.rc, r.stdout or "", r.stderr or "", dur, bool(r.timed_out))
        finally:
            try:
                node.run(f"rm -rf {shlex.quote(guest_dir)}", timeout=20)   # no cross-challenge bleed
            except Exception:  # noqa: BLE001
                pass
            self._release(node)

    def close(self):
        with self._lock:
            for env in self._envs:
                try:
                    env.teardown()
                except Exception:  # noqa: BLE001
                    pass
            self._envs, self._free = [], []


_POOL: FcPool | None = None
_POOL_LOCK = threading.Lock()


def available() -> bool:
    try:
        return FirecrackerProvider().available()
    except Exception:  # noqa: BLE001
        return False


def get_pool() -> FcPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = FcPool(size=int(os.environ.get("PEAKSTONE_FC_POOL", "1")))
        return _POOL


def run(cmd: list[str], host_cwd: Path, timeout: int, env: dict) -> tuple:
    """Entry point used by engine/sandbox._run when PEAKSTONE_SANDBOX=firecracker."""
    return get_pool().run(cmd, host_cwd, timeout, env)


def shutdown() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
            _POOL = None

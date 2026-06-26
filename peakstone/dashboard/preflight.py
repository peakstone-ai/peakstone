"""Pre-flight VRAM check before serving a model.

Serving a model that doesn't fit the free accelerator memory makes llama-server crash on load (CUDA
OOM on NVIDIA; an allocation failure on Apple Silicon). The usual cause is a previous llama-server
still holding memory. This module estimates what a model needs, compares it to what's free, and lists
our own servers that could be freed to make room. Platform specifics live in hardware.py, so this is
pure decision logic — and tested by injecting free_gb / procs.
"""
from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass, field

from . import hardware


def vram_needed_gb(entry, ctx: int | None = None) -> float | None:
    """Rough accelerator memory (GiB) a model needs to serve: weights + KV-cache + a small buffer.
    None when the file isn't present yet (size unknown — we can't check until it downloads).

    Weights are the GGUF size converted decimal-GB -> GiB so it matches hardware.gpu_free_gb (also
    GiB); KV-cache scales with ctx. `ctx` overrides the entry's configured context (so the ctx picker
    can estimate fit at an arbitrary window). Kept conservative-but-not-alarmist so a model that
    genuinely fits (e.g. a 24 GiB card running a ~21 GiB model) doesn't trip a false warning."""
    if not entry or not entry.size_gb:
        return None
    ctx = ctx or getattr(entry, "ctx", None) or 32768
    weights_gib = entry.size_gb * (10**9 / 1024**3)
    return round(weights_gib + max(0.8, ctx / 32768) + 0.5, 1)


@dataclass
class Preflight:
    free_gb: float
    need_gb: float
    freeable: list = field(default_factory=list)   # hardware.GpuProc we could kill to make room

    @property
    def freeable_gb(self) -> float:
        return round(sum(p.used_mib for p in self.freeable) / 1024, 1)

    @property
    def fits_now(self) -> bool:
        return self.need_gb <= self.free_gb

    @property
    def fits_after_free(self) -> bool:
        return self.need_gb <= self.free_gb + self.freeable_gb


def check(entry, *, free_gb: float | None = None, procs=None) -> Preflight | None:
    """A Preflight for serving `entry`, or None when the model size is unknown (not downloaded yet).
    free_gb / procs are injectable for tests; in production they come from hardware."""
    need = vram_needed_gb(entry)
    if need is None:
        return None
    free = hardware.gpu_free_gb() if free_gb is None else free_gb
    fr = hardware.freeable_gpu_procs() if procs is None else procs
    return Preflight(free_gb=free, need_gb=need, freeable=list(fr))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def free(procs, *, timeout: float = 8.0) -> int:
    """Terminate the given processes and wait for the memory to actually release (SIGTERM, then
    SIGKILL stragglers). Returns how many were signalled. POSIX signals → works on Linux and macOS.
    Blocking, so callers run it off the UI thread."""
    pids = [p.pid for p in procs]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(_alive(pid) for pid in pids):
            break
        time.sleep(0.3)
    for pid in pids:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    return len(pids)

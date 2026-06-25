"""Local hardware detection + live stats for the dashboard — stdlib only.

Linux/NVIDIA path: nvidia-smi + /proc. macOS/Apple-Silicon path: sysctl + ioreg + vm_stat (unified
memory means the GPU shares system RAM, so VRAM == total RAM and 'GPU mem used' is the driver's
in-use slice reported by IOAccelerator)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

_MAC = sys.platform == "darwin"


@dataclass
class GPU:
    index: int
    name: str
    mem_total_mib: int
    mem_used_mib: int
    util_pct: int

    @property
    def vram_gb(self) -> float:
        return round(self.mem_total_mib / 1024, 1)


@dataclass
class HardwareSnapshot:
    gpus: list[GPU]
    cpu_pct: float
    ram_total_mib: int
    ram_used_mib: int
    cores: int

    @property
    def max_vram_gb(self) -> float:
        """The largest single-GPU VRAM — the 'fits my hardware' filter the leaderboard cares about.
        On Apple Silicon this is the unified-memory budget (== total RAM)."""
        return max((g.vram_gb for g in self.gpus), default=0.0)


# --------------------------------------------------------------------------- #
# NVIDIA / Linux
# --------------------------------------------------------------------------- #
def _nvidia_gpus() -> list[GPU]:
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.stdout.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 5:
            try:
                gpus.append(GPU(int(p[0]), p[1], int(p[2]), int(p[3]), int(p[4])))
            except ValueError:
                pass
    return gpus


# --------------------------------------------------------------------------- #
# Apple Silicon / macOS
# --------------------------------------------------------------------------- #
def _sysctl(key: str) -> str | None:
    try:
        out = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _mac_gpu_perf() -> tuple[int, int]:
    """(in-use GPU memory MiB, utilization %) from IOAccelerator PerformanceStatistics — no sudo."""
    try:
        out = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return 0, 0
    # match the bare key, not the "... (driver)" variant
    used = re.search(r'"In use system memory"=(\d+)', out)
    util = re.search(r'"Device Utilization %"=(\d+)', out)
    return ((int(used.group(1)) // (1024 * 1024)) if used else 0,
            int(util.group(1)) if util else 0)


def _mac_gpus() -> list[GPU]:
    memsize = _sysctl("hw.memsize")
    if not memsize:
        return []
    try:
        total_mib = int(memsize) // (1024 * 1024)
    except ValueError:
        return []
    name = _sysctl("machdep.cpu.brand_string") or "Apple GPU"
    used_mib, util = _mac_gpu_perf()
    return [GPU(0, name, total_mib, used_mib, util)]


def _mac_mem_mib() -> tuple[int, int]:
    total = avail = 0
    memsize = _sysctl("hw.memsize")
    if memsize:
        try:
            total = int(memsize) // (1024 * 1024)
        except ValueError:
            total = 0
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
        pg = re.search(r"page size of (\d+)", out)
        page = int(pg.group(1)) if pg else 4096

        def pages(label: str) -> int:
            m = re.search(rf"{label}:\s+(\d+)\.", out)
            return int(m.group(1)) if m else 0
        # ~MemAvailable: reclaimable pages the kernel can hand back to a new allocation
        free_pages = (pages("Pages free") + pages("Pages inactive")
                      + pages("Pages speculative") + pages("Pages purgeable"))
        avail = free_pages * page // (1024 * 1024)
    except (OSError, subprocess.SubprocessError):
        avail = total
    return total, avail


# --------------------------------------------------------------------------- #
# Linux /proc helpers
# --------------------------------------------------------------------------- #
def _proc_meminfo_mib() -> tuple[int, int]:
    total = avail = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return total, avail


_prev_cpu: tuple[int, int] | None = None


def _proc_cpu_percent() -> float:
    """Busy % since the last call (needs two /proc/stat samples — first call returns 0)."""
    global _prev_cpu
    try:
        with open("/proc/stat") as f:
            vals = [int(x) for x in f.readline().split()[1:]]
        idle, total = vals[3] + vals[4], sum(vals)
    except (OSError, ValueError, IndexError):
        return 0.0
    pct = 0.0
    if _prev_cpu:
        dt, di = total - _prev_cpu[0], idle - _prev_cpu[1]
        if dt > 0:
            pct = round(100 * (dt - di) / dt, 1)
    _prev_cpu = (total, idle)
    return pct


# --------------------------------------------------------------------------- #
# platform-dispatching public API
# --------------------------------------------------------------------------- #
def query_gpus() -> list[GPU]:
    return _mac_gpus() if _MAC else _nvidia_gpus()


def _meminfo_mib() -> tuple[int, int]:
    return _mac_mem_mib() if _MAC else _proc_meminfo_mib()


def cpu_percent() -> float:
    if _MAC:
        # No cheap instantaneous counter without psutil; the 1-min load average normalised by core
        # count is a close-enough, dependency-free proxy for the meter.
        try:
            return round(min(100.0, os.getloadavg()[0] / (os.cpu_count() or 1) * 100), 1)
        except (OSError, ValueError):
            return 0.0
    return _proc_cpu_percent()


def snapshot() -> HardwareSnapshot:
    total, avail = _meminfo_mib()
    return HardwareSnapshot(gpus=query_gpus(), cpu_pct=cpu_percent(),
                            ram_total_mib=total, ram_used_mib=max(0, total - avail),
                            cores=os.cpu_count() or 0)

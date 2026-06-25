"""Local hardware detection + live stats for the dashboard — stdlib only (nvidia-smi + /proc)."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


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
        """The largest single-GPU VRAM — the 'fits my hardware' filter the leaderboard cares about."""
        return max((g.vram_gb for g in self.gpus), default=0.0)


def query_gpus() -> list[GPU]:
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


def _meminfo_mib() -> tuple[int, int]:
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


def cpu_percent() -> float:
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


def snapshot() -> HardwareSnapshot:
    total, avail = _meminfo_mib()
    return HardwareSnapshot(gpus=query_gpus(), cpu_pct=cpu_percent(),
                            ram_total_mib=total, ram_used_mib=max(0, total - avail),
                            cores=os.cpu_count() or 0)

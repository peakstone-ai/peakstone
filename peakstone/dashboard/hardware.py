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
from dataclasses import dataclass, field
from pathlib import Path

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
class GpuProc:
    """A process holding accelerator memory that we could free (always one of our own llama-servers).
    `used_mib` is GPU memory on NVIDIA, resident set size on Apple Silicon (unified memory)."""
    pid: int
    used_mib: int
    name: str = "llama-server"

    @property
    def used_gb(self) -> float:
        return round(self.used_mib / 1024, 1)


@dataclass
class HardwareSnapshot:
    gpus: list[GPU]
    cpu_pct: float
    ram_total_mib: int
    ram_used_mib: int
    cores: int
    cpu_names: list[str] = field(default_factory=lambda: ["CPU"])  # one per physical socket

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


_CPU_NAMES: list[str] | None = None


def cpu_names() -> list[str]:
    """Each physical CPU package's marketing name (e.g. ['AMD Ryzen 9 7950X']). Dual-socket boxes
    return two. Static — read once and cache."""
    global _CPU_NAMES
    if _CPU_NAMES is not None:
        return _CPU_NAMES
    names: list[str] = []
    if _MAC:
        n = _sysctl("machdep.cpu.brand_string")
        names = [n] if n else []
    else:
        sockets: dict[str, str] = {}   # physical-package id -> model name (one entry per socket)
        cur = "0"
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("physical id"):
                    cur = line.split(":", 1)[1].strip()
                elif line.startswith("model name") and cur not in sockets:
                    sockets[cur] = line.split(":", 1)[1].strip()
        except OSError:
            pass
        names = list(sockets.values())
    _CPU_NAMES = names or ["CPU"]
    return _CPU_NAMES


def snapshot() -> HardwareSnapshot:
    total, avail = _meminfo_mib()
    return HardwareSnapshot(gpus=query_gpus(), cpu_pct=cpu_percent(),
                            ram_total_mib=total, ram_used_mib=max(0, total - avail),
                            cores=os.cpu_count() or 0, cpu_names=cpu_names())


# --------------------------------------------------------------------------- #
# pre-flight VRAM: how much accelerator memory is free, and which of our servers hold it
# --------------------------------------------------------------------------- #
def gpu_free_gb() -> float:
    """Free accelerator memory budget for loading a model. On NVIDIA that's the freest GPU's spare
    VRAM; on Apple Silicon (unified memory) it's free system RAM, since weights live in RAM."""
    snap = snapshot()
    if _MAC:
        return round((snap.ram_total_mib - snap.ram_used_mib) / 1024, 1)
    g = max(snap.gpus, key=lambda x: x.mem_total_mib - x.mem_used_mib, default=None)
    return round((g.mem_total_mib - g.mem_used_mib) / 1024, 1) if g else 0.0


def _proc_is_llama(pid: int) -> bool:
    try:
        return "llama-server" in open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", "replace")
    except OSError:
        return False


def _nvidia_llama_procs() -> list[GpuProc]:
    if not shutil.which("nvidia-smi"):
        return []
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    procs = []
    for line in out.stdout.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 2:
            continue
        try:
            pid, mib = int(p[0]), int(p[1])
        except ValueError:
            continue
        if _proc_is_llama(pid):   # only ever offer to free our own servers, never arbitrary GPU apps
            procs.append(GpuProc(pid, mib))
    return procs


def _rss_mib(pid: int) -> int:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=3)
        return int(out.stdout.strip() or 0) // 1024
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _mac_llama_procs() -> list[GpuProc]:
    try:
        out = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return []
    procs = []
    for tok in out.stdout.split():
        try:
            pid = int(tok)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        procs.append(GpuProc(pid, _rss_mib(pid)))   # unified memory: RSS ≈ the budget freed
    return procs


def freeable_gpu_procs() -> list[GpuProc]:
    """Our llama-server processes currently holding accelerator memory — the ones a pre-flight check
    can offer to kill to make room. Empty when none are running."""
    return _mac_llama_procs() if _MAC else _nvidia_llama_procs()


def loaded_models() -> list[dict]:
    """Every model currently being served — one per running llama-server, parsed from its command
    line (works for any served model, TUI-launched or not). Each is {file, ctx, reasoning}
    (reasoning = the --reasoning-budget value if set, else None). Empty if nothing is serving."""
    import shlex
    try:
        pids = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True,
                              text=True, timeout=3).stdout.split()
    except Exception:  # noqa: BLE001
        return []
    found = []
    for pid in pids:
        try:
            cmd = subprocess.run(["ps", "-o", "args=", "-p", pid], capture_output=True,
                                 text=True, timeout=3).stdout.strip()
        except Exception:  # noqa: BLE001
            continue
        if "llama-server" not in cmd:
            continue
        args = shlex.split(cmd)
        out = {"file": None, "ctx": None, "reasoning": None}
        for i, a in enumerate(args):
            nxt = args[i + 1] if i + 1 < len(args) else None
            if a == "-m":
                out["file"] = nxt
            elif a == "-c" and nxt and nxt.lstrip("-").isdigit():
                out["ctx"] = int(nxt)
            elif a == "--reasoning-budget":
                out["reasoning"] = nxt
        if out["file"]:
            found.append(out)
    return found


def loaded_model() -> dict | None:
    """The first served model (back-compat single-model accessor); None if nothing is serving."""
    models = loaded_models()
    return models[0] if models else None

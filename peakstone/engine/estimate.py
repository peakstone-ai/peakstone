"""Bandwidth-aware time/data estimate for a (level, model) before committing to a run.

Resolves what the model will ACTUALLY run (level selection minus axes it can't do), then approximates
wall-clock from: generation (tokens/tps), test execution, and download (prebuilt SWE-bench image bytes
/ measured bandwidth). All constants are rough and clearly surfaced; tps/mbps are data-driven (last run
+ recorded transfers) with honest "unknown — calibrate" fallbacks.
"""
from __future__ import annotations

import json
from collections import Counter

from . import bandwidth, capabilities, keys, levels as _levels, paths, swebench
from .challenges import load_challenges

DEFAULT_TPS = 40.0          # placeholder when a model has no measured tps yet
DEFAULT_MBPS = 50.0         # placeholder when we have no bandwidth samples yet
AGENT_TURNS = 25            # rough agent-loop turns for swebench gen-token estimate
_FALLBACK_IMG_BYTES = 1.5e9  # ~1.5 GB if a prebuilt image size can't be looked up

_CODE_FAMILIES = {"humaneval", "bigcodebench", "livecodebench", "codeforces",
                  "python", "go", "rust", "javascript", "typescript"}


def _last_tps(model: str) -> float | None:
    try:
        hist = json.loads((keys.KEY_DIR / "repro-history.json").read_text())
    except (OSError, ValueError):
        return None
    for h in reversed(hist if isinstance(hist, list) else []):
        if h.get("model") == model and h.get("your_tps"):
            return float(h["your_tps"])
    return None


def _gen_tokens(family: str, level) -> int:
    if family == "swebench":
        return AGENT_TURNS * 1500 if level.agent else 2000
    if family == "aime":
        return 3000
    if family in ("tool-calling", "injection"):
        return 500
    if family in ("refusal", "hallucination", "security"):
        return 400
    return 600


def _exec_sec(family: str, level) -> float:
    if family == "swebench":
        return 40 if level.prebuilt else 210
    if family in _CODE_FAMILIES:
        return 5
    return 1


def _swebench_download_bytes(swe_challenges: list, level) -> float:
    """Σ prebuilt image sizes for the selected swebench instances (sample a few, extrapolate)."""
    if not (level.prebuilt and swe_challenges):
        return 0.0
    sizes = []
    for c in swe_challenges[:3]:   # sample a few image sizes (bounded Hub calls), extrapolate
        try:
            inst = json.loads((c.dir / "instance.json").read_text())
        except (OSError, ValueError):
            continue
        sz = swebench.image_size(inst.get("image", "")) if inst.get("image") else None
        if sz:
            sizes.append(sz)
    avg = (sum(sizes) / len(sizes)) if sizes else _FALLBACK_IMG_BYTES
    return avg * len(swe_challenges)


def estimate(level_name: str, model: str) -> dict:
    _, levels = _levels.load_levels()
    level = levels.get(level_name)
    if not level:
        raise ValueError(f"unknown level {level_name!r}")
    corpus = load_challenges(paths.challenges_dir())
    sel = set(_levels.resolve(level, corpus))
    caps = capabilities.effective_capabilities(model)
    selected = [c for c in corpus if c.id in sel and _levels.relevant(c.family, caps)]
    by_family = Counter(c.family for c in selected)

    tps = _last_tps(model)
    mbps = bandwidth.estimated_mbps()
    gen_min = sum(n * _gen_tokens(f, level) for f, n in by_family.items()) / (tps or DEFAULT_TPS) / 60
    exec_min = sum(n * _exec_sec(f, level) for f, n in by_family.items()) / 60
    dl_bytes = _swebench_download_bytes([c for c in selected if c.family == "swebench"], level)
    dl_gb = dl_bytes / 1e9
    dl_min = (dl_bytes / 1e9) * 1000 / (mbps or DEFAULT_MBPS) / 60

    unknowns = []
    if tps is None:
        unknowns.append("tps unknown — run `--level smoke` to calibrate")
    if mbps is None and dl_bytes > 0:
        unknowns.append("bandwidth unknown — a download will calibrate")

    return {
        "level": level_name, "model": model, "n_challenges": len(selected),
        "by_family": dict(by_family.most_common()),
        "gen_min": round(gen_min, 1), "exec_min": round(exec_min, 1),
        "download_gb": round(dl_gb, 1), "download_min": round(dl_min, 1),
        "total_min": round(gen_min + exec_min + dl_min, 1),
        "tps": tps, "mbps": mbps, "unknowns": unknowns,
        "settings": {"judge": level.judge, "agent": level.agent, "prebuilt": level.prebuilt},
    }


def format_estimate(e: dict) -> str:
    t = e["total_min"]
    dur = f"{t/60:.1f} h" if t >= 90 else f"{t:.0f} min"
    fam = "  ".join(f"{k}:{v}" for k, v in e["by_family"].items())
    lines = [f"{e['level']} on {e['model']}: {e['n_challenges']} challenges  ·  ~{dur}"
             + (f"  ·  ~{e['download_gb']} GB download" if e["download_gb"] else ""),
             f"  {fam}",
             f"  gen ~{e['gen_min']}m  exec ~{e['exec_min']}m  download ~{e['download_min']}m"
             f"  (tps {e['tps'] or '?'}  bw {e['mbps'] or '?'} MB/s)"]
    lines += [f"  ! {u}" for u in e["unknowns"]]
    return "\n".join(lines)

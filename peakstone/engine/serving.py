"""Launch / health-check / stop a single llama-server for one registered model.

These are the low-level serving primitives shared by every consumer that needs to bring a model
up on the GPU: the dashboard's reproduce flow, and the model-swapping gateway (`peakstone serve`).
They were originally inlined in ``dashboard/reproduce.py``; they live here now so an engine-level
service can use them WITHOUT importing the Textual/HF dashboard layer. ``reproduce.py`` re-exports
them, so its public API is unchanged.

Everything here is stdlib-only (subprocess + urllib) and the external steps are injectable, so the
orchestration is testable without a GPU.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import paths, vram


def serve_sh() -> Path:
    """Path to serve/serve.sh — the per-model llama-server launcher (override via PEAKSTONE_SERVE)."""
    return paths.serve_dir() / "serve.sh"


def serve_log_path(name: str) -> Path:
    return paths.repo_root() / "results" / f"serve-{name}.log"


def serve_log_tail(name: str, lines: int = 12) -> str:
    """Last few lines of a model's serve log — the crash reason (e.g. CUDA OOM) when it won't start."""
    p = serve_log_path(name)
    if not p.exists():
        return ""
    return "\n".join(p.read_text(errors="replace").splitlines()[-lines:]).strip()


def reasoning_budget(reasoning) -> str | None:
    """Map a reasoning override to a --reasoning-budget value (via PEAKSTONE_REASONING_BUDGET):
    'off'→0 (no thinking), 'on'→-1 (think freely), a positive int N → cap thinking at N tokens then
    force the answer (guarantees answer room; the numeric thinking budget). None = leave the model's
    configured budget. Numeric caps require model/llama.cpp support for a positive budget."""
    if reasoning == "off":
        return "0"
    if reasoning == "on":
        return "-1"
    if isinstance(reasoning, int) and reasoning > 0:
        return str(reasoning)
    return None


def serve(name: str, *, popen=subprocess.Popen, ctx: int | None = None,
          reasoning=None) -> subprocess.Popen:
    """Spawn `bash serve/serve.sh <name>` (one llama-server), logging stdout+stderr to
    results/serve-<name>.log so a failed launch (OOM, missing binary) is diagnosable. The child runs
    in its own session so the whole process group can be killed later."""
    log = serve_log_path(name)
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ}
    if ctx:
        env["PEAKSTONE_CTX"] = str(ctx)   # serve.sh + the bundle pick this up
    rb = reasoning_budget(reasoning)      # off=0, on=-1, int=cap thinking at N tokens
    if rb is not None:
        env["PEAKSTONE_REASONING_BUDGET"] = rb
    # close the parent's handle once spawned — the child keeps its own dup (no fd leak per serve).
    with open(log, "wb") as logf:
        return popen(["bash", str(serve_sh()), name], cwd=str(paths.repo_root()), stdout=logf,
                     stderr=subprocess.STDOUT, start_new_session=True, env=env)


def wait_healthy(port: int, *, timeout: float = 180, opener=urllib.request.urlopen, proc=None) -> bool:
    """Poll /health until the server answers. Fails fast if the serve process exits first (a crashed
    llama-server otherwise leaves us polling a dead port for the whole timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and getattr(proc, "poll", lambda: None)() is not None:
            return False   # server process died before binding the port
        try:
            with opener(f"http://localhost:{port}/health", timeout=3) as r:
                if getattr(r, "status", 200) == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return False


def _kill(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def stop(proc) -> None:
    """Kill the serve process group (frees VRAM). No-op if it already exited."""
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


@dataclass(frozen=True)
class ServeModel:
    """One model's serving config from serve/models.toml (the fields needed to launch + reach it)."""
    name: str
    port: int | None
    ctx: int | None
    file: str | None = None
    flags: str = ""
    mmproj: str | None = None   # vision projector GGUF (repo-relative); when set, serve.sh passes
                                # --mmproj so the model accepts image input (multimodal).

    @property
    def multimodal(self) -> bool:
        """True if a vision projector is declared (so the model can take images)."""
        return bool(self.mmproj)

    @property
    def mmproj_present(self) -> bool:
        return bool(self.mmproj and (paths.repo_root() / self.mmproj).exists())

    @property
    def present(self) -> bool:
        """Whether everything needed to load is on disk so a request can load it without a download:
        the GGUF, plus the vision projector when the model is multimodal."""
        if not (self.file and (paths.repo_root() / self.file).exists()):
            return False
        return self.mmproj_present if self.mmproj else True


def load_registry() -> dict[str, ServeModel]:
    """Parse serve/models.toml into {name: ServeModel}. The same file serve.sh reads. Empty if the
    registry is absent (e.g. a bare wheel with no checkout)."""
    mt = paths.models_toml()
    if not mt.exists():
        return {}
    data = tomllib.loads(mt.read_text())
    return {n: ServeModel(n, m.get("port"), m.get("ctx"), m.get("file"), m.get("flags", ""),
                          m.get("mmproj"))
            for n, m in data.items()}


# --- context-window selection ------------------------------------------------------------------
# Which ctx to serve a model at. Precedence: an explicit ctx in models.toml ("something specified")
# wins; otherwise ROUGH-estimate the largest window that fits this GPU's VRAM analytically from the
# GGUF geometry (engine/vram.py). It's a cold-start guess — errs small, snaps down, and warns when
# the fit is tight or a configured ctx looks too big. The long-term plan is to lean on observed ctx
# from other runs on similar hardware (the leaderboard) and use this estimate only when no data yet.

DEFAULT_CTX = 32768          # last-resort window when neither configured nor estimable
MIN_CTX = 4096               # smallest window worth attempting when a model barely/doesn't fit


def _weights_bytes(path: Path) -> int:
    """Total on-disk weight bytes. For a split GGUF (…-00001-of-000NN.gguf) sum ALL shards — llama.cpp
    loads every shard, so sizing on shard 1 alone underestimates VRAM and over-estimates the ctx."""
    if not re.search(r"-(\d{5})-of-(\d{5})\.gguf$", path.name):
        return path.stat().st_size
    parts = sorted(path.parent.glob(re.sub(r"-\d{5}-of-\d{5}\.gguf$", "-*-of-*.gguf", path.name)))
    return sum(p.stat().st_size for p in parts) or path.stat().st_size


def detect_vram_gib(*, run=subprocess.run) -> float | None:
    """Total VRAM of the largest GPU in GiB (macOS: unified memory == total RAM). None if unknown."""
    try:
        if sys.platform == "darwin":
            out = run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / 1024 ** 3
        out = run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                  capture_output=True, text=True, timeout=10)
        return max(int(x) for x in out.stdout.split()) / 1024   # MiB -> GiB, largest GPU
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class CtxChoice:
    ctx: int | None          # window to serve at; None => caller falls back to DEFAULT_CTX
    source: str              # "configured" | "estimated" | "fallback"
    warning: str | None = None


def resolve_ctx(model: ServeModel, *, vram_gib: float | None = None,
                _read_geometry=vram.read_geometry, _detect=detect_vram_gib) -> CtxChoice:
    """Pick the serving ctx for `model` (see module note). Pure given the injected GGUF/VRAM readers."""
    flags = model.flags or ""
    # --n-cpu-moe puts part of the weights on the host CPU, which this analytical estimate doesn't
    # model — so don't second-guess an offloaded model; trust its configured ctx. (These are the
    # don't-fit-on-GPU models; sizing them from observed runs is the follow-up.)
    offloaded = "--n-cpu-moe" in flags
    est = None
    if not offloaded and model.file:
        path = paths.repo_root() / model.file
        gib = vram_gib if vram_gib is not None else _detect()
        if path.exists() and gib:
            try:
                geom = _read_geometry(path)
                mmproj = ((paths.repo_root() / model.mmproj).stat().st_size
                          if model.mmproj_present else 0)
                k, v = vram.cache_types_from_flags(flags)
                est = vram.estimate_max_ctx(geom=geom, weights_bytes=_weights_bytes(path),
                                            vram_gib=gib, k_type=k, v_type=v, mmproj_bytes=mmproj)
            except Exception:  # noqa: BLE001  -- unreadable/odd GGUF: just fall back
                est = None
    if model.ctx:                                   # configured -> respect it, warn if it won't fit
        warn = None
        if est is not None and model.ctx > max(est.max_ctx, 0):
            warn = (f"weights (~{est.weights_gib:.0f}GB) leave no VRAM for KV on this GPU — will likely OOM; "
                    f"use --n-cpu-moe or a smaller quant" if est.max_ctx == 0 else
                    f"configured ctx {model.ctx} > ~{est.max_ctx} that fits this GPU's VRAM — may OOM on load")
        return CtxChoice(model.ctx, "configured", warn)
    if est is not None and est.max_ctx > 0:
        warn = (f"tight VRAM fit — only {est.kv_budget_gib:.1f}GB left for KV; may OOM"
                if not est.capped_by_native and est.kv_budget_gib < 1.0 else None)
        return CtxChoice(est.max_ctx, "estimated", warn)
    if est is not None:                             # est computed but nothing fits (max_ctx == 0)
        # Don't silently fall through to DEFAULT_CTX — that's the exact over-budget window that OOMs.
        # Surface it (candidate negative data when the load actually crashes) and try the minimum.
        return CtxChoice(MIN_CTX, "estimated",
                         f"weights (~{est.weights_gib:.0f}GB) exceed this GPU's VRAM — will likely OOM at any "
                         f"ctx; use --n-cpu-moe or a smaller quant")
    reason = ("--n-cpu-moe model: ctx not auto-estimated" if offloaded
              else "no GGUF geometry / VRAM info; using default ctx")
    return CtxChoice(None, "fallback", reason)


# --- running the benchmark engine as a subprocess ----------------------------------------------
# Shared by the dashboard's reproduce flow and the gateway's job worker so the command, watchdog,
# and stall-detection are identical. `gateway` (a base URL) routes generation through `peakstone
# serve` instead of per-model llama-server ports — used by the daemon, which owns serving.

def judge_model_name() -> str | None:
    """The configured local judge ([judge] in engine/config.toml): its registry name when judging
    is enabled, else None (no judge pass is chained)."""
    try:
        jcfg = tomllib.loads(paths.config_path().read_text()).get("judge", {})
    except Exception:  # noqa: BLE001
        return None
    if not jcfg.get("enabled", True):
        return None
    return jcfg.get("model") or None


def level_needs_judge(level: str | None) -> bool:
    """Does this level's definition declare judge=true? (The daemon runs generation-only and
    grades in a separate judge-LAST pass — one GPU can't hold the bench model and the judge.)"""
    if not level:
        return False
    try:
        from .levels import load_levels
        _, levels = load_levels()
        lv = levels.get(level)
        return bool(lv and lv.judge)
    except Exception:  # noqa: BLE001
        return False


def build_judge_cmd(src: Path, judge_model: str, *, out: Path,
                    gateway: str | None = None) -> tuple[list[str], float]:
    """Build the judge-LAST pass over a finished generation run: `runner --judge-only <src>`
    grades the judge/both rows with `judge_model` (riding the gateway, which swaps the judge in
    ONCE) and --bundle re-emits the run's signed bundle with judge model + params recorded."""
    cmd = ["python", "-u", "-m", "peakstone.engine.runner", "--judge-only", str(src),
           "--judge-model", judge_model, "--bundle", "--out", str(out)]
    if gateway:
        cmd += ["--gateway", gateway]
    return cmd, 24 * 3600.0   # grading a full level is many small judge calls; generous cap


def build_runner_cmd(name: str, ids: list[str] | None = None, *, level: str | None = None,
                     out: Path, max_tokens: int | None = None,
                     gateway: str | None = None) -> tuple[list[str], float]:
    """Build the `python -m peakstone.engine.runner …` command + a hard timeout for one bench run.
    Generation-only (--no-judge): one model at a time, so judging is a separate judge-last pass."""
    cmd = ["python", "-u", "-m", "peakstone.engine.runner", "--models", name, "--bundle",
           "--stream-output", "--out", str(out)]
    if gateway:
        cmd += ["--gateway", gateway]
    if max_tokens:
        cmd += ["--max-tokens", str(max_tokens)]   # generation budget; recorded in the bundle
    if level:
        # the runner resolves the level's selection + settings; --prune-images keeps prebuilt image
        # disk bounded. Levels span minutes..weeks, so give it a very generous cap.
        cmd += ["--level", level, "--no-judge", "--prune-images"]
        timeout = 14 * 24 * 3600.0
    else:
        cmd += ["--no-judge"]
        if ids:
            # pass the selection via a file (not --ids) so an arbitrarily large set never hits argv.
            ids_file = out / "selection.ids"
            ids_file.write_text("\n".join(ids))
            cmd += ["--ids-file", str(ids_file)]
        timeout = 1800.0 if (ids and len(ids) <= 50) else 6 * 3600.0
    return cmd, timeout


def stream_runner(cmd: list[str], *, out: Path, timeout: float, env_extra: dict | None = None,
                  log=lambda s: None, popen=subprocess.Popen, on_proc=None) -> dict | None:
    """Spawn the runner, stream its stdout line-by-line to `log`, and return the parsed bundle.json
    (or None). A hard timeout and a stall watchdog (no output for PEAKSTONE_STALL_SECONDS) kill a
    wedged run so the caller fails gracefully instead of hanging."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}   # flush each progress line as it happens
    if env_extra:
        env.update(env_extra)
    proc = popen(cmd, cwd=str(paths.repo_root()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 text=True, bufsize=1, env=env, start_new_session=True)
    if on_proc:
        on_proc(proc)          # register so a cancel can kill the run mid-flight
    killer = threading.Timer(timeout, lambda: _kill(proc))   # hard cap even if the child goes silent
    killer.start()
    stall = float(os.environ.get("PEAKSTONE_STALL_SECONDS", "900"))
    last = [time.monotonic()]

    _poll = getattr(proc, "poll", lambda: 0)   # a stub proc without poll() -> watchdog is a no-op
    def _watchdog():
        while _poll() is None:
            time.sleep(15)
            if time.monotonic() - last[0] > stall:
                log(f"!! no output for {int(stall)}s — run appears stuck; killing it and moving on")
                _kill(proc)
                return

    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        for line in proc.stdout:
            last[0] = time.monotonic()
            log(line.rstrip("\n"))
    finally:
        killer.cancel()
        proc.wait()
    bundle = out / "bundle.json"
    return json.loads(bundle.read_text()) if bundle.exists() else None

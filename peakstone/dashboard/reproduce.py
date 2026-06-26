"""Reproduce a leaderboard run on local hardware: ensure the model is present (download if not) →
serve it → bench it → compare your tok/s to the published number.

The external steps (serve / health / bench / stop) are injectable so the orchestration is testable
without a GPU; the real path uses serve/serve.sh + peakstone.engine.runner on a host with llama-server.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import models
from .models import REPO

SERVE_SH = REPO / "serve" / "serve.sh"


@dataclass
class ReproduceResult:
    model: str
    ok: bool
    your_tps: float | None = None
    published_tps: float | None = None
    code_score: float | None = None
    passed: int = 0
    total: int = 0
    note: str = ""
    bundle: dict | None = None    # the signed bundle, for one-key submission to the leaderboard

    @property
    def tps_ratio(self) -> float | None:
        if self.your_tps and self.published_tps:
            return round(self.your_tps / self.published_tps, 2)
        return None


def serve_log_path(name: str) -> Path:
    return REPO / "results" / f"serve-{name}.log"


def serve_log_tail(name: str, lines: int = 12) -> str:
    """Last few lines of a model's serve log — the crash reason (e.g. CUDA OOM) when it won't start."""
    p = serve_log_path(name)
    if not p.exists():
        return ""
    return "\n".join(p.read_text(errors="replace").splitlines()[-lines:]).strip()


def serve(name: str, *, popen=subprocess.Popen, ctx: int | None = None) -> subprocess.Popen:
    log = serve_log_path(name)
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ}
    if ctx:
        env["PEAKSTONE_CTX"] = str(ctx)   # serve.sh + the bundle pick this up
    # capture stdout+stderr to a file so a failed launch (OOM, missing binary) is diagnosable
    return popen(["bash", str(SERVE_SH), name], cwd=str(REPO), stdout=open(log, "wb"),
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


def bench(name: str, ids: list[str] | None = None, *, level: str | None = None,
          out_dir: Path | None = None, log=lambda s: None, popen=subprocess.Popen, on_proc=None,
          ctx: int | None = None) -> dict | None:
    """Run the engine over the selection, streaming the runner's per-challenge output line-by-line to
    `log` so the dashboard can show progress live (each challenge solving + its ✓/✗ result)."""
    out = Path(out_dir) if out_dir else (REPO / "results" / f"repro-{name}")
    out.mkdir(parents=True, exist_ok=True)
    # -u + PYTHONUNBUFFERED so the child flushes each progress line as it happens (live streaming).
    cmd = ["python", "-u", "-m", "peakstone.engine.runner", "--models", name, "--bundle",
           "--stream-output", "--out", str(out)]
    if level:
        # the runner resolves the level's selection + settings (judge/agent/prebuilt); stream-prune
        # so prebuilt image disk stays bounded.
        cmd += ["--level", level, "--prune-images"]
        timeout = 14 * 24 * 3600   # levels span minutes..weeks; let it run
    else:
        cmd += ["--no-judge"]
        if ids:
            # pass the selection via a file (not --ids) so an arbitrarily large set never hits argv.
            ids_file = out / "selection.ids"
            ids_file.write_text("\n".join(ids))
            cmd += ["--ids-file", str(ids_file)]
        timeout = 1800 if (ids and len(ids) <= 50) else 6 * 3600
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if ctx:
        env["PEAKSTONE_CTX"] = str(ctx)   # the runner's bundle records this as the served context
    proc = popen(cmd, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 text=True, bufsize=1, env=env, start_new_session=True)
    if on_proc:
        on_proc(proc)          # register so a cancel can kill the benchmark mid-run
    killer = threading.Timer(timeout, lambda: _kill(proc))   # hard cap even if the child goes silent
    killer.start()
    try:
        for line in proc.stdout:
            log(line.rstrip("\n"))
    finally:
        killer.cancel()
        proc.wait()
    bundle = out / "bundle.json"
    return json.loads(bundle.read_text()) if bundle.exists() else None


def _kill(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def stop(proc) -> None:
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            try:
                proc.kill()
            except OSError:
                pass


def reproduce(name: str, *, challenge_ids: list[str] | None = None, level: str | None = None,
              published_tps: float | None = None, on_proc=None, on_dl_progress=None, ctx: int | None = None,
              log=lambda s: None, _serve=serve, _wait=wait_healthy, _bench=bench, _stop=stop,
              _download=models.download) -> ReproduceResult:
    entry = models.load_registry().get(name)
    if entry is None:
        return ReproduceResult(name, False, note=f"{name} not in serve/models.toml — add it first")
    if not entry.present:
        log("model file missing; downloading…")
        if not _download(entry, log, progress=on_dl_progress, on_proc=on_proc):
            return ReproduceResult(name, False, published_tps=published_tps, note="download failed")
    log(f"serving {name} on :{entry.port}{f' (ctx {ctx})' if ctx else ''} …")
    proc = _serve(name, ctx=ctx)
    if on_proc:
        on_proc(proc)          # register so the run can be cancelled (killed) mid-flight
    try:
        if not _wait(entry.port, proc=proc):
            died = proc is not None and getattr(proc, "poll", lambda: None)() is not None
            if died:
                tail = serve_log_tail(name)
                hint = "CUDA out of memory" if "out of memory" in tail.lower() else \
                       "is llama-server installed and the GPU free?"
                log(f"serve failed:\n{tail}" if tail else "serve process exited")
                note = f"llama-server for {name} exited before serving — {hint}"
            else:
                note = "model never became healthy in time (is llama-server installed / GPU free?)"
            return ReproduceResult(name, False, published_tps=published_tps, note=note)
        log(f"benchmarking ({'level ' + level if level else 'selection'}) …")
        bundle = _bench(name, challenge_ids, level=level, log=log, on_proc=on_proc, ctx=ctx)
    finally:
        _stop(proc)
        log("stopped serving")
    if not bundle:
        return ReproduceResult(name, False, published_tps=published_tps, note="benchmark produced no bundle")

    results = bundle.get("results", [])
    tps = [r["tok_per_s"] for r in results if isinstance(r.get("tok_per_s"), (int, float))]
    codes = [r["score"]["final"] for r in results
             if r.get("verification") == "deterministic-tests" and isinstance(r.get("score"), dict)]
    passed = sum(r.get("score", {}).get("passed", 0) for r in results if isinstance(r.get("score"), dict))
    total = sum(r.get("score", {}).get("total", 0) for r in results if isinstance(r.get("score"), dict))
    return ReproduceResult(
        name, True,
        your_tps=round(sum(tps) / len(tps), 1) if tps else None,
        published_tps=published_tps,
        code_score=round(sum(codes) / len(codes), 3) if codes else None,
        passed=passed, total=total, note="done", bundle=bundle)

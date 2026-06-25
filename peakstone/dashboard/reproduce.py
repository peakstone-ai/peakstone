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


def serve(name: str, *, popen=subprocess.Popen) -> subprocess.Popen:
    return popen(["bash", str(SERVE_SH), name], cwd=str(REPO), stdout=subprocess.DEVNULL,
                 stderr=subprocess.STDOUT, start_new_session=True)


def wait_healthy(port: int, *, timeout: float = 180, opener=urllib.request.urlopen) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener(f"http://localhost:{port}/health", timeout=3) as r:
                if getattr(r, "status", 200) == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    return False


def bench(name: str, ids: list[str] | None = None, *, level: str | None = None,
          runner=subprocess.run, out_dir: Path | None = None) -> dict | None:
    out = Path(out_dir) if out_dir else (REPO / "results" / f"repro-{name}")
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["python", "-m", "peakstone.engine.runner", "--models", name, "--bundle", "--out", str(out)]
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
    runner(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout)
    bundle = out / "bundle.json"
    return json.loads(bundle.read_text()) if bundle.exists() else None


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
              published_tps: float | None = None,
              log=lambda s: None, _serve=serve, _wait=wait_healthy, _bench=bench, _stop=stop,
              _download=models.download) -> ReproduceResult:
    entry = models.load_registry().get(name)
    if entry is None:
        return ReproduceResult(name, False, note=f"{name} not in serve/models.toml — add it first")
    if not entry.present:
        log("model file missing; downloading…")
        if not _download(entry, log):
            return ReproduceResult(name, False, published_tps=published_tps, note="download failed")
    log(f"serving {name} on :{entry.port} …")
    proc = _serve(name)
    try:
        if not _wait(entry.port):
            return ReproduceResult(name, False, published_tps=published_tps,
                                   note="model never became healthy (is llama-server installed?)")
        log(f"benchmarking ({'level ' + level if level else 'selection'}) …")
        bundle = _bench(name, challenge_ids, level=level) if level else _bench(name, challenge_ids)
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

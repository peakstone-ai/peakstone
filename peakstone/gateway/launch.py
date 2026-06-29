"""Launch helpers: detect a running gateway and spawn one detached.

Used two ways:
- `peakstone serve --detach` → start the daemon in the background and return to the shell.
- The TUI on startup → auto-spawn a gateway if none is answering, so a local OpenAI endpoint is
  available while you work. Because it's detached (its own session), quitting the TUI leaves it
  running — that's the decoupling: the daemon outlives its clients.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from ..engine import paths


def base_url(host: str = "127.0.0.1", port: int = 11434) -> str:
    # 0.0.0.0 isn't a connectable address — probe loopback when the daemon binds all interfaces.
    reach = "127.0.0.1" if host in ("", "0.0.0.0") else host
    return f"http://{reach}:{port}"


def is_running(host: str = "127.0.0.1", port: int = 11434, *, timeout: float = 1.0) -> bool:
    """True if a gateway answers /health at host:port."""
    try:
        with urllib.request.urlopen(f"{base_url(host, port)}/health", timeout=timeout) as r:
            return getattr(r, "status", 200) == 200
    except Exception:  # noqa: BLE001
        return False


def gateway_log_path() -> Path:
    return paths.repo_root() / "results" / "gateway.log"


def spawn_detached(host: str = "127.0.0.1", port: int = 11434, idle_timeout: float = 0.0,
                   *, popen=subprocess.Popen) -> subprocess.Popen:
    """Start `python -m peakstone.gateway` in its own session (survives the parent), logging to
    results/gateway.log."""
    log = gateway_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "peakstone.gateway", "--host", host, "--port", str(port),
           "--idle-timeout", str(idle_timeout)]
    with open(log, "ab") as logf:
        return popen(cmd, cwd=str(paths.repo_root()), stdout=logf, stderr=subprocess.STDOUT,
                     start_new_session=True, env={**os.environ})


def ensure_running(host: str = "127.0.0.1", port: int = 11434, idle_timeout: float = 0.0,
                   *, wait: float = 15.0) -> bool:
    """Ensure a gateway is up at host:port, spawning one detached if not. Returns True once it answers
    /health (or was already running); False if it didn't come up in `wait` seconds."""
    if is_running(host, port):
        return True
    spawn_detached(host, port, idle_timeout)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_running(host, port):
            return True
        time.sleep(0.5)
    return False

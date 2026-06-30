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
import tomllib
import urllib.request
from pathlib import Path

from ..engine import paths


def _gateway_block() -> dict:
    """The committed [gateway] block, overlaid by the per-machine ~/.peakstone/config.toml override
    (its keys win) so a machine can opt into LAN/open settings without editing the tracked config."""
    g: dict = {}
    for p in (paths.config_path(), paths.user_config_path()):
        try:
            g.update(tomllib.loads(p.read_text()).get("gateway", {}))
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return g


def load_gateway_config() -> dict:
    """Read the [gateway] block (host/port/idle_timeout_s/open). This is the single source of truth
    for where the gateway binds; launch + client defaults all derive from it. The committed defaults
    in engine/config.toml are overridden per-machine by ~/.peakstone/config.toml (see _gateway_block)."""
    g = _gateway_block()
    return {
        "host": g.get("host", "127.0.0.1"),
        "port": int(g.get("port", 12434)),
        "idle_timeout_s": float(g.get("idle_timeout_s", 0)),
        "open": bool(g.get("open", False)),   # TUI auto-spawn disables auth when true (trusted LAN)
    }


def _resolve(host, port):
    """Fill in host/port from config when a caller passes None — so the configured port is honoured
    even on the no-arg ensure_running() the TUI uses."""
    if host is None or port is None:
        cfg = load_gateway_config()
        host = cfg["host"] if host is None else host
        port = cfg["port"] if port is None else port
    return host, port


def base_url(host: str | None = None, port: int | None = None) -> str:
    host, port = _resolve(host, port)
    # 0.0.0.0 isn't a connectable address — probe loopback when the daemon binds all interfaces.
    reach = "127.0.0.1" if host in ("", "0.0.0.0") else host
    return f"http://{reach}:{port}"


def is_running(host: str | None = None, port: int | None = None, *, timeout: float = 1.0) -> bool:
    """True if a gateway answers /health at host:port."""
    host, port = _resolve(host, port)
    try:
        with urllib.request.urlopen(f"{base_url(host, port)}/health", timeout=timeout) as r:
            return getattr(r, "status", 200) == 200
    except Exception:  # noqa: BLE001
        return False


def gateway_log_path() -> Path:
    return paths.repo_root() / "results" / "gateway.log"


def spawn_detached(host: str | None = None, port: int | None = None, idle_timeout: float = 0.0,
                   *, open_access: bool = False, popen=subprocess.Popen) -> subprocess.Popen:
    """Start `python -m peakstone.gateway` in its own session (survives the parent), logging to
    results/gateway.log. `open_access` forwards --open (auth disabled)."""
    host, port = _resolve(host, port)
    log = gateway_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "peakstone.gateway", "--host", host, "--port", str(port),
           "--idle-timeout", str(idle_timeout)]
    if open_access:
        cmd.append("--open")
    with open(log, "ab") as logf:
        return popen(cmd, cwd=str(paths.repo_root()), stdout=logf, stderr=subprocess.STDOUT,
                     start_new_session=True, env={**os.environ})


def ensure_running(host: str | None = None, port: int | None = None, idle_timeout: float = 0.0,
                   *, wait: float = 15.0, open_access: bool | None = None) -> bool:
    """Ensure a gateway is up at host:port, spawning one detached if not. Returns True once it answers
    /health (or was already running); False if it didn't come up in `wait` seconds. `open_access`
    forwards --open (auth off) to a spawned daemon; None => take it from config ([gateway].open)."""
    host, port = _resolve(host, port)
    if open_access is None:
        open_access = load_gateway_config()["open"]
    if is_running(host, port):
        return True
    spawn_detached(host, port, idle_timeout, open_access=open_access)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_running(host, port):
            return True
        time.sleep(0.5)
    return False

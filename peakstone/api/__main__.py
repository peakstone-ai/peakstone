"""`python -m peakstone.api` — run the submission/leaderboard API with host/port from config.

Reads the committed [api] block in engine/config.toml, overlaid by the per-machine override at
$PEAKSTONE_HOME/config.toml (~/.peakstone/config.toml) — the same mechanism as [gateway]. So to reach
the API from your LAN (phone, another machine, the web app), drop this in ~/.peakstone/config.toml
without editing the tracked file:

    [api]
    host = "0.0.0.0"

Precedence: --host/--port flags > PEAKSTONE_API_HOST/PEAKSTONE_API_PORT env > user config > committed
config > defaults (127.0.0.1:8000). Binding 0.0.0.0 exposes the API to the whole network — ingest is
signature-verified, but account/admin endpoints are reachable too, so only do it on a trusted LAN.
"""
from __future__ import annotations

import argparse
import os
import tomllib

from ..engine import paths


def load_api_config() -> dict:
    """[api] host/port from the committed config, overlaid by the per-machine override, then env."""
    cfg: dict = {}
    for p in (paths.config_path(), paths.user_config_path()):
        try:
            cfg.update(tomllib.loads(p.read_text()).get("api", {}))
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return {
        "host": os.environ.get("PEAKSTONE_API_HOST", cfg.get("host", "127.0.0.1")),
        "port": int(os.environ.get("PEAKSTONE_API_PORT", cfg.get("port", 8000))),
    }


def main(argv=None) -> int:
    cfg = load_api_config()
    ap = argparse.ArgumentParser(prog="python -m peakstone.api",
                                 description="Run the Peakstone submission/leaderboard API")
    ap.add_argument("--host", default=cfg["host"], help="bind address (0.0.0.0 exposes it on the LAN)")
    ap.add_argument("--port", type=int, default=cfg["port"])
    ap.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = ap.parse_args(argv)

    import uvicorn
    lan = args.host in ("", "0.0.0.0")
    reach = "127.0.0.1" if lan else args.host
    print(f">>> Peakstone API on http://{reach}:{args.port}" + ("  (LAN: 0.0.0.0)" if lan else ""))
    uvicorn.run("peakstone.api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

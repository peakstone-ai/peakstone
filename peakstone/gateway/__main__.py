"""`python -m peakstone.gateway` — run the model-swapping OpenAI gateway.

Also the target of the `peakstone serve` subcommand (see peakstone/dashboard/app.py:main).
"""
from __future__ import annotations

import argparse
import sys

from .app import load_gateway_config, run


def main(argv: list[str] | None = None) -> int:
    cfg = load_gateway_config()
    ap = argparse.ArgumentParser(
        prog="peakstone serve",
        description="Standing llama-swap-style OpenAI gateway over serve/models.toml. The request's "
                    "`model` field selects which model is loaded; the backend llama-server is swapped "
                    "on demand. Point any OpenAI client at http://<host>:<port>/v1.")
    ap.add_argument("--host", default=cfg["host"],
                    help=f"bind address (default {cfg['host']}; use 0.0.0.0 to expose on the LAN)")
    ap.add_argument("--port", type=int, default=cfg["port"],
                    help=f"front port (default {cfg['port']})")
    ap.add_argument("--idle-timeout", type=float, default=cfg["idle_timeout_s"], metavar="SECONDS",
                    help="unload the model after this many idle seconds to free VRAM (0 = never)")
    ap.add_argument("--detach", action="store_true",
                    help="start the daemon in the background and return to the shell")
    args = ap.parse_args(argv)
    if args.detach:
        from .launch import base_url, spawn_detached
        proc = spawn_detached(args.host, args.port, args.idle_timeout)
        print(f">>> peakstone gateway started (pid {proc.pid}) on {base_url(args.host, args.port)}/v1")
        return 0
    run(host=args.host, port=args.port, idle_timeout=args.idle_timeout)
    return 0


def jobs_main(argv: list[str] | None = None) -> int:
    """`peakstone jobs …` — drive the daemon's benchmark queue headless (no TUI), e.g. over SSH."""
    from ..dashboard import client

    ap = argparse.ArgumentParser(prog="peakstone jobs",
                                 description="Queue/list/cancel benchmark jobs on the gateway daemon.")
    ap.add_argument("--gateway", default=client.GATEWAY_DEFAULT, help="gateway base URL")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="queue a benchmark run")
    p_add.add_argument("model")
    g = p_add.add_mutually_exclusive_group()
    g.add_argument("--level", help="run a named level (smoke/quick/standard/…)")
    g.add_argument("--ids", help="comma-separated challenge ids")
    p_add.add_argument("--ctx", type=int)
    p_add.add_argument("--reasoning", help="off | on | <int> thinking-token cap")
    p_add.add_argument("--budget", type=int, help="max generation tokens")
    sub.add_parser("list", help="list jobs")
    p_cancel = sub.add_parser("cancel", help="cancel a queued/running job")
    p_cancel.add_argument("id")
    p_logs = sub.add_parser("logs", help="stream a job's log")
    p_logs.add_argument("id")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "add":
            spec: dict = {"model": args.model}
            if args.level:
                spec["level"] = args.level
            if args.ids:
                spec["ids"] = [s for s in args.ids.split(",") if s]
            if args.ctx:
                spec["ctx"] = args.ctx
            if args.reasoning is not None:
                spec["reasoning"] = int(args.reasoning) if args.reasoning.isdigit() else args.reasoning
            if args.budget:
                spec["budget"] = args.budget
            jid = client.enqueue_job(spec, base_url=args.gateway)
            print(f"queued {jid}")
        elif args.cmd == "list":
            for j in client.list_jobs(base_url=args.gateway):
                s = j.get("summary") or {}
                extra = f"  {s.get('passed','')}/{s.get('total','')}" if s.get("total") else ""
                print(f"{j['id']}  {j['status']:<11} {(j.get('spec') or {}).get('model','?')}{extra}")
        elif args.cmd == "cancel":
            print("cancelled" if client.cancel_job(args.id, base_url=args.gateway) else "not cancellable")
        elif args.cmd == "logs":
            for line in client.stream_job_log(args.id, base_url=args.gateway):
                print(line)
    except client.APIError as e:
        print(f"gateway error: {e} (is `peakstone serve` running?)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

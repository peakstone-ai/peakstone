"""`peakstone update` — upgrade the installed client, picking the right command for how it was installed.

Deliberately explicit (user-invoked), not a silent self-update: it just runs the correct upgrade for
your install (pipx / pip), or tells you the git command for a dev checkout.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from ..engine import versions


def _install_kind() -> str:
    """How this peakstone was installed: 'pipx', 'editable' (dev checkout), or 'pip'."""
    if "pipx" in sys.prefix.lower() or "pipx" in sys.executable.lower():
        return "pipx"
    try:
        from importlib.metadata import distribution
        durl = (distribution("peakstone").read_text("direct_url.json") or "").replace(" ", "").lower()
        if '"editable":true' in durl:
            return "editable"
    except Exception:  # noqa: BLE001
        pass
    return "pip"


def update_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="peakstone update", description="Upgrade the Peakstone client")
    ap.add_argument("--check", action="store_true", help="report the installed version only; don't upgrade")
    args = ap.parse_args(argv)

    installed, kind = versions.pkg_version(), _install_kind()
    print(f"peakstone {installed}  (install: {kind})")
    if args.check:
        return 0
    if kind == "editable":
        print("dev/editable install — update with:  git pull   "
              "(then `pip install -e '.[dashboard]'` if dependencies changed)")
        return 0
    cmd = (["pipx", "upgrade", "peakstone"] if kind == "pipx"
           else [sys.executable, "-m", "pip", "install", "-U", "peakstone[dashboard]"])
    print("running:", " ".join(cmd))
    try:
        rc = subprocess.call(cmd)
    except FileNotFoundError as e:
        print(f"could not run the upgrader ({e}); update manually with `pipx upgrade peakstone` "
              f"or `pip install -U 'peakstone[dashboard]'`", file=sys.stderr)
        return 1
    if rc == 0:
        # refresh the corpus to match the just-installed version (runs the NEW peakstone, so it syncs
        # that version's tag). Best-effort — the dashboard also auto-syncs a missing/stale corpus.
        print("\nrefreshing the challenge corpus …")
        try:
            subprocess.call(["peakstone", "corpus", "sync"])
        except FileNotFoundError:
            print("run `peakstone corpus sync` to refresh the challenge corpus.")
    return rc


if __name__ == "__main__":
    raise SystemExit(update_main())

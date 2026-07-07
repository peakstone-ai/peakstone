"""`peakstone submit <bundle.json> …` — POST signed result bundles to the leaderboard API.

The bundle is already signed by the engine (`peakstone bench --bundle`); this just ships it.
201 = accepted, 409 = already on the board (both count as success)."""
from __future__ import annotations

import argparse
import json
import sys

from .client import API_DEFAULT, APIError, submit_bundle


def submit_main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="peakstone submit",
        description="Submit signed result bundle(s) to the public leaderboard.")
    ap.add_argument("bundle", nargs="+", help="path(s) to bundle.json files")
    ap.add_argument("--api", default=API_DEFAULT, help="API base URL")
    args = ap.parse_args(argv)

    rc = 0
    for path in args.bundle:
        try:
            b = json.load(open(path))
        except (OSError, json.JSONDecodeError) as e:
            print(f"{path}: cannot read bundle ({e})", file=sys.stderr)
            rc = 1
            continue
        try:
            status, detail = submit_bundle(args.api, b)
        except APIError as e:
            print(f"{path}: API unreachable ({e})", file=sys.stderr)
            rc = 1
            continue
        note = {201: "accepted", 409: "already submitted"}.get(status, "REJECTED")
        print(f"{path}: {status} {note} {detail[:140] if status not in (201, 409) else ''}".rstrip())
        if status not in (201, 409):
            rc = 1
    return rc

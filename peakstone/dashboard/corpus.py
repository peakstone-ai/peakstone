"""``peakstone corpus sync`` — fetch the challenge corpus from GitHub for pip-installed clients.

The wheel ships the dashboard + engine but not the corpus, so `paths.challenges_dir()` falls back to
``$PEAKSTONE_HOME/challenges``. This command populates that dir from the committed ``challenges/``
tree in the GitHub repo (native challenges + HumanEval + a BigCodeBench slice + GSM8K). Only
committed challenges are in the GitHub tarball, so copyright-encumbered/private sets are never
fetched. Pin to the client's version tag by default so the corpus and client stay in lockstep
(reproducible content_hash); fall back to ``main`` if that tag isn't published yet.
"""
from __future__ import annotations

import argparse
import io
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from peakstone import __version__
from peakstone.engine import paths

REPO = "peakstone-ai/peakstone"


def _tarball_url(ref: str) -> str:
    # ref is a GitHub archive ref path, e.g. "tags/v0.1.1" or "heads/main"
    return f"https://github.com/{REPO}/archive/refs/{ref}.tar.gz"


def _fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=180) as r:  # noqa: S310 (trusted host)
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _extract_challenges(blob: bytes, dest: Path) -> int:
    """Extract only the ``<top>/challenges/**`` subtree into ``dest`` (atomic swap). Returns the
    number of challenges (meta.toml files) written."""
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            if "/challenges/" not in m.name:
                continue
            rel = m.name.split("/challenges/", 1)[1]
            if not rel:
                continue
            target = (tmp / rel).resolve()
            if not str(target).startswith(str(tmp.resolve())):
                continue                       # path-traversal guard
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(m)
                if src is None:
                    continue
                with src:
                    target.write_bytes(src.read())
                if rel.endswith("meta.toml"):
                    n += 1
    dest_bak = dest.with_name(dest.name + ".bak")
    if dest.exists():
        if dest_bak.exists():
            shutil.rmtree(dest_bak)
        dest.rename(dest_bak)
    tmp.rename(dest)
    if dest_bak.exists():
        shutil.rmtree(dest_bak)
    return n


def corpus_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="peakstone corpus",
                                 description="Manage the local challenge corpus")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("sync", help="download the challenge corpus from GitHub")
    s.add_argument("--ref", default=None,
                   help="git ref to fetch (default: the client's version tag, else main). "
                        "Examples: --ref tags/v0.1.1 | --ref heads/main")
    s.add_argument("--dest", default=None,
                   help="corpus dir (default: $PEAKSTONE_HOME/challenges)")
    args = ap.parse_args(argv)
    if args.cmd != "sync":
        ap.print_help()
        return 2

    dest = Path(args.dest) if args.dest else paths.home_dir() / "challenges"
    refs = [args.ref] if args.ref else [f"tags/v{__version__}", "heads/main"]
    for ref in refs:
        url = _tarball_url(ref)
        print(f"fetching {url} ...")
        blob = _fetch(url)
        if blob is None:
            print(f"  {ref}: not found, trying next")
            continue
        n = _extract_challenges(blob, dest)
        print(f"synced {n} challenges -> {dest}  (ref {ref})")
        print("run the suite with:  peakstone-bench --level standard --models <your-model>")
        return 0
    print("could not fetch the corpus (no matching ref found on GitHub).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(corpus_main(sys.argv[1:]))

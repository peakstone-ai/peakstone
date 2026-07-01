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
            # only the top-level <top>/challenges/** tree — NOT e.g. web/app/challenges/[id]/
            parts = m.name.split("/", 2)
            if len(parts) < 3 or parts[1] != "challenges":
                continue
            rel = parts[2]
            if not rel or rel.split("/", 1)[0][:1] in ("_", "."):   # skip _archived/ etc.
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


MARKER = ".peakstone-sync-ref"   # records which git ref the local corpus was synced from


def _ref_default() -> str:
    return f"tags/v{__version__}"


def sync(ref: str | None = None, dest=None, log=print) -> tuple[int, str]:
    """Fetch + extract the corpus into ``dest`` ($PEAKSTONE_HOME/challenges by default). Records the
    ref in a marker file so staleness is detectable. Returns (n_challenges, ref_used); raises
    RuntimeError if no ref resolved on GitHub."""
    dest = Path(dest) if dest else paths.home_dir() / "challenges"
    for r in ([ref] if ref else [_ref_default(), "heads/main"]):
        log(f"fetching {_tarball_url(r)} ...")
        blob = _fetch(_tarball_url(r))
        if blob is None:
            log(f"  {r}: not found, trying next")
            continue
        n = _extract_challenges(blob, dest)
        try:
            (dest / MARKER).write_text(r)
        except Exception:  # noqa: BLE001
            pass
        return n, r
    raise RuntimeError("could not fetch the corpus (no matching ref found on GitHub).")


def local_ref(dest=None) -> str | None:
    """The git ref the local corpus was last synced from (None if never synced)."""
    dest = Path(dest) if dest else paths.home_dir() / "challenges"
    m = dest / MARKER
    try:
        return m.read_text().strip() if m.exists() else None
    except Exception:  # noqa: BLE001
        return None


def should_autosync() -> bool:
    """True when the dashboard should auto-(re)sync on startup: only in pip-installed mode (the corpus
    resolves to $PEAKSTONE_HOME/challenges, not a repo checkout or explicit override), and only when
    it's missing/empty or was synced from a different client version."""
    home_corpus = paths.home_dir() / "challenges"
    if paths.challenges_dir() != home_corpus:
        return False                       # repo checkout / PEAKSTONE_REPO / PEAKSTONE_CHALLENGES → user-managed
    if not home_corpus.exists() or not any(home_corpus.rglob("meta.toml")):
        return True                        # missing / empty
    return local_ref(home_corpus) != _ref_default()   # stale: synced from another version


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
    try:
        n, ref = sync(args.ref, args.dest, log=print)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    dest = Path(args.dest) if args.dest else paths.home_dir() / "challenges"
    print(f"synced {n} challenges -> {dest}  (ref {ref})")
    print("run the suite with:  peakstone-bench --level standard --models <your-model>")
    return 0


if __name__ == "__main__":
    sys.exit(corpus_main(sys.argv[1:]))

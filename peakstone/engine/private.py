"""Commit-and-reveal for private challenges (vision §7 Idea 2) — the crypto core + bundle shape.

A private challenge (any challenge dir under a `private/` directory, e.g. `challenges/private/…`,
which is gitignored) never leaves the box: its bundle rows carry ONLY the score numbers, safe
metadata, and a salted **commitment** `sha256(salt ‖ meta.toml ‖ spec.md ‖ tests/** ‖ reference/**)`.
The server can timestamp that sealed claim now (`submitted_at` is the integrity anchor); revealing
the content + salt later proves the challenge existed unaltered BEFORE any model could have trained
on it — held-out by construction, not just by date.

The salt (random 32 bytes, hex, at `<challenge>/.peakstone-salt`) prevents dictionary attacks on
the commitment: without it, a low-entropy spec could be brute-forced from the hash. It must be kept
(and kept private) until reveal — losing it means the commitment can never be opened. Dot-files are
excluded from the hash, so the salt file never hashes itself.

Layers: this module = pure functions (commit, verify, gate). Bundle integration lives in
engine/bundle.py (private rows are redacted at production time). The server-side
`committed-private` trust tier + `peakstone reveal` flow are a later slice.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path

SALT_FILE = ".peakstone-salt"
_PREFIX = "sha256:"


def is_private_dir(d: Path) -> bool:
    """A challenge is private iff it lives under a directory named `private` (the gitignored
    convention: challenges/private/…). Path-based, not a meta flag — a flag typo silently
    publishing someone's private challenge content is the failure mode to make impossible."""
    return "private" in Path(d).parts


def ensure_salt(d: Path) -> str:
    """The challenge's salt (hex), created on first use. Keep this file until reveal."""
    p = Path(d) / SALT_FILE
    if p.is_file():
        salt = p.read_text().strip()
        if salt:
            return salt
    salt = secrets.token_hex(32)
    p.write_text(salt + "\n")
    return salt


def _content_files(d: Path) -> list[Path]:
    """The committed content: meta.toml + spec.md + tests/** + reference/** (sorted, dot-files
    excluded everywhere — the salt file and editor droppings must never hash themselves in)."""
    d = Path(d)
    files = [d / "meta.toml", d / "spec.md"]
    for sub in ("tests", "reference"):
        if (d / sub).is_dir():
            files += sorted((d / sub).rglob("*"))
    return [f for f in files
            if f.is_file() and not any(part.startswith(".") for part in f.relative_to(d).parts)]


def content_files_map(d: Path) -> dict[str, str]:
    """{relpath: text} of a challenge dir's committed content — the exact payload a reveal ships."""
    d = Path(d)
    return {f.relative_to(d).as_posix(): f.read_text(errors="replace") for f in _content_files(d)}


def commitment_from_files(files: dict[str, str], salt: str) -> str:
    """The salted commitment over a {relpath: text} map — the ONE hashing definition, shared by the
    author side (dir walk) and the server side (reveal verification). `sha256:<hex>` over
    salt ‖ (relpath ‖ NUL ‖ utf-8 bytes) in sorted-relpath order; dot-paths and non-content paths
    are ignored so a sloppy reveal payload can't change the hash."""
    h = hashlib.sha256()
    h.update(bytes.fromhex(salt))
    for rel in sorted(files):
        parts = rel.split("/")
        if any(p.startswith(".") for p in parts):
            continue
        if rel not in ("meta.toml", "spec.md") and parts[0] not in ("tests", "reference"):
            continue
        h.update(rel.encode())
        h.update(b"\0")
        h.update(files[rel].encode())
    return _PREFIX + h.hexdigest()


def commitment(d: Path, salt: str | None = None) -> str:
    """The salted content commitment for a challenge dir: `sha256:<hex>` over
    salt ‖ (relpath ‖ NUL ‖ bytes) for every content file. Deterministic given (content, salt)."""
    d = Path(d)
    salt = salt if salt is not None else ensure_salt(d)
    return commitment_from_files(content_files_map(d), salt)


def public_content_hash(files: dict[str, str]) -> str:
    """The PUBLIC (unsalted) challenge content hash a revealed challenge gets in the corpus —
    same definition as bundle._hash_challenge_dir: meta.toml + spec.md + tests/** (reference and
    salt excluded), relpath ‖ NUL ‖ bytes in sorted order."""
    h = hashlib.sha256()
    for rel in sorted(files):
        parts = rel.split("/")
        if any(p.startswith(".") for p in parts):
            continue
        if rel not in ("meta.toml", "spec.md") and parts[0] != "tests":
            continue
        h.update(rel.encode())
        h.update(b"\0")
        h.update(files[rel].encode())
    return h.hexdigest()


def verify_reveal(d: Path, salt: str, committed: str) -> bool:
    """Does this revealed content + salt open the commitment? Constant-time compare."""
    try:
        return hmac.compare_digest(commitment(Path(d), salt=salt), committed)
    except (ValueError, OSError):   # malformed salt hex / unreadable dir
        return False


def gate_reveal(d: Path) -> tuple[dict, dict]:
    """The reference-must-pass gate a revealed challenge must clear before it can join the public
    corpus — the same author-side validation `peakstone propose` runs (structure checks + the
    reference solution passing its own tests in the sandbox). Returns (meta, validation);
    raises propose.ProposalError with the reason otherwise."""
    from .propose import validate_dir
    return validate_dir(Path(d))


def private_commitments(challenges_dir: Path) -> dict[str, str]:
    """challenge id -> commitment for every private challenge in the corpus (salts created on
    first use). Mirrors bundle.challenge_hashes' walk; `_`/`.` dirs skipped the same way."""
    import tomllib
    root = Path(challenges_dir)
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for meta in root.rglob("meta.toml"):
        d = meta.parent
        rel = d.relative_to(root).parts
        if any(p[:1] in ("_", ".") for p in rel) or not is_private_dir(d):
            continue
        try:
            cid = tomllib.loads(meta.read_text())["id"]
        except Exception:  # noqa: BLE001
            continue
        out[cid] = commitment(d)
    return out


def reveal_main(argv=None) -> int:
    """`peakstone reveal <challenge-dir>` — open a private challenge's commitment on the platform.

    Runs the reference-must-pass gate locally (the API never executes untrusted code), then posts
    content + salt to POST /reveals. On success the challenge joins the public corpus with
    published_at = the reveal date, and every sealed result that committed to it starts counting
    (held-out by construction for models released before today)."""
    import argparse
    import json
    import os
    import sys
    import urllib.request

    ap = argparse.ArgumentParser(
        prog="peakstone reveal",
        description="Reveal a private (commit-and-reveal) challenge: verify locally, publish "
                    "content+salt, and unlock the sealed results that committed to it.")
    ap.add_argument("challenge_dir", help="the private challenge directory (needs its .peakstone-salt)")
    ap.add_argument("--api", default=os.environ.get("PEAKSTONE_API_URL")
                    or os.environ.get("PEAKSTONE_API") or "https://peakstone.ai/api")
    ap.add_argument("--skip-gate", action="store_true",
                    help="skip the local reference-must-pass run (only if you just ran it)")
    args = ap.parse_args(argv)

    d = Path(args.challenge_dir)
    salt_file = d / SALT_FILE
    if not salt_file.is_file():
        print(f"!! {salt_file} not found — a salt is created when the challenge is first bundled; "
              "without it the commitment cannot be opened", file=sys.stderr)
        return 2
    salt = salt_file.read_text().strip()

    validation = None
    if args.skip_gate:
        print("skipping the local reference gate (--skip-gate)")
    else:
        from .propose import ProposalError
        try:
            _, validation = gate_reveal(d)
            print(f"reference gate: passed ({validation['passed']}/{validation['total']})")
        except ProposalError as e:
            print(f"!! reference gate failed: {e}", file=sys.stderr)
            return 1

    files = content_files_map(d)
    com = commitment_from_files(files, salt)
    body: dict = {"salt": salt, "files": files, "validation": validation}
    try:
        from . import keys
        priv, pub = keys.load_or_create_keypair()
        body["pubkey"] = pub
        body["signature"] = keys.sign(priv, f"reveal:{com}".encode())
    except Exception:  # noqa: BLE001 — attribution is optional; the commitment is the proof
        pass

    req = urllib.request.Request(f"{args.api.rstrip('/')}/reveals",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"!! reveal rejected: HTTP {e.code}: {e.read().decode()[:400]}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"!! API unreachable: {e}", file=sys.stderr)
        return 1
    print(f"revealed {out['challenge_id']}  ({out['n_results_revealed']} sealed result(s) now count; "
          f"published_at={out['published_at']})")
    print("NOTE: the challenge content is now PUBLIC — models released after today are "
          "contaminated on it, and your held-out point is locked in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(reveal_main())

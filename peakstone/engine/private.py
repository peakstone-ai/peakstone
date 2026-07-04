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


def commitment(d: Path, salt: str | None = None) -> str:
    """The salted content commitment for a challenge dir: `sha256:<hex>` over
    salt ‖ (relpath ‖ NUL ‖ bytes) for every content file. Deterministic given (content, salt)."""
    d = Path(d)
    salt = salt if salt is not None else ensure_salt(d)
    h = hashlib.sha256()
    h.update(bytes.fromhex(salt))
    for f in _content_files(d):
        h.update(f.relative_to(d).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
    return _PREFIX + h.hexdigest()


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

"""Author a challenge *proposal* from a local challenge directory (PLAN.md §9 P2a).

The open corpus lets anyone propose a challenge; an admin canonizes it later. A proposal is the
same shape as an in-repo challenge (meta.toml + spec.md + tests/ + reference/), bundled into one
content-addressed, ed25519-signed JSON so the moderation API can dedupe + attribute it.

Validation is author-side by design: the API never executes untrusted test/reference code (it runs
on a host holding DB creds). So this tool runs the reference against the tests *here*, on the
author's machine, and records the pass/fail as a self-reported claim. A reviewer re-runs the same
check locally (`python -m engine.propose --check <dir>`) before approving.

  python -m engine.propose challenges/python/15-foo            # -> proposal.json (signed)
  python -m engine.propose --check challenges/python/15-foo    # validate only, no signing
"""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from . import keys
from .bundle import _sha256_bytes, canonical_bytes
from .challenges import load_challenges
from .sandbox import run_tests

PROPOSAL_VERSION = "1"
_REQUIRED_META = ("id", "title", "language", "difficulty")
_SUPPORTED_LANGS = {"python", "javascript", "typescript", "go", "rust"}
# files (besides spec.md) that travel with the proposal, as {relpath: content}
_TRACKED = ("meta.toml",)


class ProposalError(ValueError):
    """The directory isn't a valid, self-consistent challenge."""


def _gather_files(d: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for name in _TRACKED:
        if (d / name).is_file():
            files[name] = (d / name).read_text()
    for sub in ("tests", "reference"):
        base = d / sub
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    files[str(f.relative_to(d))] = f.read_text()
    return files


def _content_hash(p: dict) -> str:
    """Hash the challenge *content* — not the author's validation claim or signature, so two authors
    proposing identical challenges collide (dedupe)."""
    core = {k: v for k, v in p.items() if k not in ("validation", "submitter", "content_hash")}
    return _sha256_bytes(canonical_bytes(core))


def _load_cfg() -> dict:
    cfg_path = Path(__file__).resolve().parent / "config.toml"
    if cfg_path.exists():
        try:
            return tomllib.loads(cfg_path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return {}


def validate_dir(challenge_dir: Path) -> tuple[dict, dict]:
    """Structural checks + a local reference run. Returns (meta, validation). Raises ProposalError."""
    d = Path(challenge_dir)
    if not (d / "meta.toml").is_file():
        raise ProposalError(f"{d}: missing meta.toml")
    meta = tomllib.loads((d / "meta.toml").read_text())
    missing = [k for k in _REQUIRED_META if not meta.get(k)]
    if missing:
        raise ProposalError(f"meta.toml missing required keys: {', '.join(missing)}")
    if meta["language"] not in _SUPPORTED_LANGS:
        raise ProposalError(f"unsupported language {meta['language']!r}")
    if not (d / "spec.md").is_file():
        raise ProposalError(f"{d}: missing spec.md")
    if not (d / "tests").is_dir() or not any((d / "tests").glob("*")):
        raise ProposalError(f"{d}: tests/ is empty or missing")
    if not (d / "reference").is_dir() or not any((d / "reference").rglob("*")):
        raise ProposalError(f"{d}: reference/ is empty or missing (needed to validate the challenge)")

    ch = load_challenges(d)
    if not ch:
        raise ProposalError(f"{d}: could not load as a challenge")
    ch = ch[0]
    ref = ch.reference_files()
    if not ref:
        raise ProposalError(f"{d}: no reference files")
    run = run_tests(ch, ref, _load_cfg())
    validation = {
        "reference_passes": bool(run.ok),
        "passed": run.passed, "total": run.total,
        "note": run.note or None,
    }
    if not run.ok:
        raise ProposalError(
            f"reference solution does NOT pass its own tests ({run.passed}/{run.total}; "
            f"rc={run.returncode}). Fix the challenge before proposing.\n{(run.stderr or run.stdout)[-1500:]}")
    return meta, validation


def build_proposal(challenge_dir: Path, *, sign: bool = True) -> dict:
    d = Path(challenge_dir)
    meta, validation = validate_dir(d)
    p: dict = {
        "proposal_version": PROPOSAL_VERSION,
        "slug": meta["id"],
        "title": meta["title"],
        "language": meta["language"],
        "category": meta.get("category"),
        "difficulty": int(meta["difficulty"]),
        "scoring": meta.get("scoring", "tests"),
        "solution_file": meta.get("solution_file"),
        "timeout": int(meta.get("timeout", 30)),
        "spec": (d / "spec.md").read_text(),
        "files": _gather_files(d),
    }
    p["content_hash"] = _content_hash(p)
    p["validation"] = validation
    if sign:
        priv, pub = keys.load_or_create_keypair()
        p["submitter"] = {"pubkey": pub, "signature": keys.sign(priv, p["content_hash"].encode())}
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Author/validate a challenge proposal.")
    ap.add_argument("challenge_dir", type=Path)
    ap.add_argument("--check", action="store_true", help="validate only (no signing, no output file)")
    ap.add_argument("--out", type=Path, help="write the signed proposal JSON here (default: proposal.json)")
    args = ap.parse_args(argv)
    try:
        if args.check:
            meta, validation = validate_dir(args.challenge_dir)
            print(f"OK  {meta['id']}: reference passes {validation['passed']}/{validation['total']}")
            return 0
        p = build_proposal(args.challenge_dir, sign=True)
    except ProposalError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    out = args.out or (Path.cwd() / "proposal.json")
    out.write_text(json.dumps(p, indent=2, ensure_ascii=False))
    print(f"wrote {out}  (slug={p['slug']}, hash={p['content_hash'][:12]}, "
          f"reference {p['validation']['passed']}/{p['validation']['total']})")
    print(f"submit:  curl -X POST $PEAKSTONE_API/proposals -H 'content-type: application/json' --data @{out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

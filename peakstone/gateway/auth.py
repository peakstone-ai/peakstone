"""Gateway auth — a single bearer token, with loopback exempted.

The daemon is meant to be reachable on the LAN (e.g. coding from a laptop against the GPU box), so
non-loopback requests must present `Authorization: Bearer <token>`. Requests from localhost are
exempt — the local TUI, CLI, and the job-runner (which calls the gateway on 127.0.0.1) need no token.

The token is auto-generated on first use and persisted at ~/.peakstone/gateway_token (mode 0600,
same handling as the ed25519 signing key in engine/keys.py). `PEAKSTONE_GATEWAY_TOKEN` overrides the
file (handy for ephemeral/containerised runs).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

_HOME = Path(os.environ.get("PEAKSTONE_HOME", str(Path.home() / ".peakstone")))
TOKEN_PATH = _HOME / "gateway_token"

LOOPBACK = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def load_or_create_token() -> str:
    """Return the gateway token: $PEAKSTONE_GATEWAY_TOKEN if set, else the persisted file, generating
    and writing one (0600) on first use."""
    env = os.environ.get("PEAKSTONE_GATEWAY_TOKEN")
    if env:
        return env
    if TOKEN_PATH.exists():
        tok = TOKEN_PATH.read_text().strip()
        if tok:
            return tok
    tok = "pk-" + secrets.token_urlsafe(32)
    _HOME.mkdir(parents=True, exist_ok=True)
    os.chmod(_HOME, 0o700)
    # atomic 0600 create (O_EXCL) — never a world-readable window for the secret. If two processes
    # race, the loser falls back to reading the winner's file.
    try:
        fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(tok)
    except FileExistsError:
        tok = TOKEN_PATH.read_text().strip()
    return tok


def client_is_loopback(request: Request) -> bool:
    return bool(request.client and request.client.host in LOOPBACK)


def bearer_token(request: Request) -> str | None:
    """Extract the token from `Authorization: Bearer <token>`, if present."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def make_auth_dependency(token: str):
    """Build a FastAPI dependency enforcing the token, exempting loopback. `token` empty disables auth
    entirely (open gateway)."""

    async def require_auth(request: Request) -> None:
        if not token:
            return
        if client_is_loopback(request):
            return
        presented = bearer_token(request)
        if presented and secrets.compare_digest(presented, token):
            return
        raise HTTPException(status_code=401,
                            detail="missing or invalid bearer token (set Authorization: Bearer <token>)")

    return require_auth

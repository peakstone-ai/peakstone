"""Ed25519 signing identity for result bundles.

The keypair is the ROOT identity for a submitter — durable and portable. Auth providers (GitHub,
etc.) only bind an account to this pubkey server-side; this module knows nothing about them. A
submitter can run fully pseudonymously with just a key.

Key lives at ~/.peakstone/key.ed25519 (private, raw 32 bytes, base64, mode 0600). The matching
public key is derived on load and embedded (base64) in every bundle's `submitter.pubkey`.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

KEY_DIR = Path(os.environ.get("PEAKSTONE_HOME", str(Path.home() / ".peakstone")))
KEY_PATH = KEY_DIR / "key.ed25519"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def load_or_create_keypair() -> tuple[Ed25519PrivateKey, str]:
    """Return (private_key, public_key_b64), generating + persisting a key on first use."""
    if KEY_PATH.exists():
        try:
            priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(KEY_PATH.read_text().strip()))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"corrupt signing key at {KEY_PATH}; remove it to regenerate ({e})")
    else:
        priv = Ed25519PrivateKey.generate()
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(KEY_DIR, 0o700)
        # create with 0600 atomically (O_EXCL) — never a world-readable window for the private key
        fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(_b64(priv.private_bytes_raw()))
    return priv, public_key_b64(priv)


def public_key_b64(priv: Ed25519PrivateKey) -> str:
    return _b64(priv.public_key().public_bytes_raw())


def sign(priv: Ed25519PrivateKey, data: bytes) -> str:
    """Detached signature over `data`, base64."""
    return _b64(priv.sign(data))


def verify(pubkey_b64: str, signature_b64: str, data: bytes) -> bool:
    """Verify a base64 signature against a base64 ed25519 public key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        pub.verify(base64.b64decode(signature_b64), data)
        return True
    except Exception:  # noqa: BLE001  (InvalidSignature or malformed input)
        return False

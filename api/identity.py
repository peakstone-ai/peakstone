"""Account ⇄ key binding — pluggable auth providers over the ed25519 root identity (PLAN §5/§8).

The signing key is the ROOT identity. An *account* is optional and additive: a provider (GitHub
first) attests "this external account is real", and the key holder proves "I own this key" by
signing a server-issued nonce. Both proofs in one binding call → we create/find an internal User,
record an IdentityLink (keyed by internal user_id, never the provider's id → no lock-in), and point
the Key at that user. New providers are just another entry in PROVIDERS; nothing else changes.
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import timedelta, timezone

from sqlalchemy import select

from engine import keys as eng_keys

from . import models
from .models import _utcnow

CHALLENGE_TTL = timedelta(minutes=10)


class BindError(ValueError):
    """Binding rejected (maps to HTTP 4xx)."""


# --- admin (moderation) authority ----------------------------------------------------------------
# Admins are an allowlist of ed25519 pubkeys (env PEAKSTONE_ADMIN_KEYS, comma-separated). Moderation
# actions are signed by an admin key over the action payload — same root identity as everything else,
# no passwords/sessions.

def admin_keys() -> set[str]:
    return {k.strip() for k in os.environ.get("PEAKSTONE_ADMIN_KEYS", "").split(",") if k.strip()}


def is_admin(pubkey: str) -> bool:
    return pubkey in admin_keys()


def verify_admin_action(pubkey: str, signature: str, message: str) -> bool:
    """True iff `pubkey` is an admin AND it signed `message`."""
    return is_admin(pubkey) and eng_keys.verify(pubkey, signature, message.encode())


# --- key-ownership proof -------------------------------------------------------------------------

def issue_key_challenge(db, pubkey: str) -> models.KeyChallenge:
    """Mint a single-use nonce the key must sign to prove ownership."""
    ch = models.KeyChallenge(pubkey=pubkey, nonce=secrets.token_urlsafe(24),
                             expires_at=_utcnow() + CHALLENGE_TTL)
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


def _consume_key_proof(db, pubkey: str, nonce: str, signature: str) -> None:
    """Verify (pubkey signed nonce) against a live challenge, then consume it. Raises on failure."""
    ch = db.scalar(select(models.KeyChallenge)
                   .where(models.KeyChallenge.nonce == nonce, models.KeyChallenge.pubkey == pubkey))
    if not ch:
        raise BindError("unknown or already-used challenge")
    # SQLite hands back naive datetimes even for tz-aware columns; coerce to UTC before comparing
    exp = ch.expires_at if ch.expires_at.tzinfo else ch.expires_at.replace(tzinfo=timezone.utc)
    expired = exp < _utcnow()
    # Consume durably BEFORE validating: a failed attempt raises and rolls back the rest of the
    # binding, so the deletion must be committed on its own or a bad nonce could be retried forever.
    db.delete(ch)
    db.commit()
    if expired:
        raise BindError("challenge expired")
    if not eng_keys.verify(pubkey, signature, nonce.encode()):
        raise BindError("key signature verification failed")


# --- providers -----------------------------------------------------------------------------------

class GitHubProvider:
    """GitHub OAuth web flow. Configured via env so it's a no-op until secrets are set."""
    name = "github"

    def configured(self) -> bool:
        return bool(os.environ.get("PEAKSTONE_GITHUB_CLIENT_ID")
                    and os.environ.get("PEAKSTONE_GITHUB_CLIENT_SECRET"))

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        q = urllib.parse.urlencode({
            "client_id": os.environ["PEAKSTONE_GITHUB_CLIENT_ID"],
            "redirect_uri": redirect_uri, "scope": "read:user", "state": state,
            "allow_signup": "true",
        })
        return f"https://github.com/login/oauth/authorize?{q}"

    def exchange(self, code: str, redirect_uri: str) -> dict:
        """OAuth code → {account_id, handle}. Network call; monkeypatched in tests."""
        token = self._post_json("https://github.com/login/oauth/access_token", {
            "client_id": os.environ["PEAKSTONE_GITHUB_CLIENT_ID"],
            "client_secret": os.environ["PEAKSTONE_GITHUB_CLIENT_SECRET"],
            "code": code, "redirect_uri": redirect_uri,
        }).get("access_token")
        if not token:
            raise BindError("github did not return an access token")
        user = self._get_json("https://api.github.com/user", token)
        return {"account_id": str(user["id"]), "handle": user.get("login")}

    @staticmethod
    def _post_json(url: str, data: dict) -> dict:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    @staticmethod
    def _get_json(url: str, token: str) -> dict:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())


PROVIDERS: dict[str, GitHubProvider] = {"github": GitHubProvider()}


def get_provider(name: str):
    p = PROVIDERS.get(name)
    if p is None:
        raise BindError(f"unknown provider {name!r}")
    if not p.configured():
        raise BindError(f"provider {name!r} is not configured on this server")
    return p


# --- the binding ---------------------------------------------------------------------------------

def bind(db, *, provider: str, pubkey: str, nonce: str, signature: str,
         code: str, redirect_uri: str) -> dict:
    """Bind `pubkey` to the account proven by `code` at `provider`. Idempotent per (provider,account)
    and per key: re-binding the same pair just returns the existing linkage."""
    prov = get_provider(provider)
    _consume_key_proof(db, pubkey, nonce, signature)         # proof 1: key ownership
    account = prov.exchange(code, redirect_uri)              # proof 2: account ownership

    # find-or-create the internal user via the provider account (so a second key binds to the SAME
    # user, and the user keeps the same id across providers)
    link = db.scalar(select(models.IdentityLink).where(
        models.IdentityLink.provider == provider,
        models.IdentityLink.provider_account_id == account["account_id"]))
    if link:
        user = db.get(models.User, link.user_id)
    else:
        user = models.User(handle=account.get("handle"))
        db.add(user)
        db.flush()
        db.add(models.IdentityLink(user_id=user.id, provider=provider,
                                   provider_account_id=account["account_id"]))

    key = db.scalar(select(models.Key).where(models.Key.pubkey == pubkey))
    if not key:                                              # bind even a not-yet-seen key
        key = models.Key(pubkey=pubkey)
        db.add(key)
        db.flush()
    if key.user_id is not None and key.user_id != user.id:
        raise BindError("key is already bound to a different account")
    key.user_id = user.id
    db.commit()
    return {"user_id": user.id, "handle": user.handle, "provider": provider,
            "provider_account_id": account["account_id"]}


def account_summary(db, pubkey: str) -> dict | None:
    """Public view of who a key belongs to: the user + their linked providers (no secrets)."""
    key = db.scalar(select(models.Key).where(models.Key.pubkey == pubkey))
    if not key or key.user_id is None:
        return None
    user = db.get(models.User, key.user_id)
    links = db.scalars(select(models.IdentityLink)
                       .where(models.IdentityLink.user_id == user.id)).all()
    return {"user_id": user.id, "handle": user.handle,
            "providers": [{"provider": l.provider, "account_id": l.provider_account_id}
                          for l in links],
            "keys": [k.pubkey for k in db.scalars(
                select(models.Key).where(models.Key.user_id == user.id)).all()]}

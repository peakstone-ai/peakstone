"""`peakstone login` — link your local signing key to a GitHub account in one step.

Your ed25519 signing key (engine/keys) is your root identity; binding it to a GitHub handle means your
submitted runs are attributed to you and can be community-verified (only account-bound reproductions
count toward the ranked board). The flow, all local — the private key never leaves your machine:

  1. ask the API for the GitHub OAuth consent URL, open it in your browser
  2. catch the redirect on a loopback server and grab the OAuth `code`
  3. prove you own the key by signing a server-issued nonce
  4. POST both proofs to /account/bind  ->  "linked as @you"

--manual prints the URL and reads the code you paste back (headless / no local browser). The loopback
callback URL (default http://127.0.0.1:53682/callback) must be registered on the server's GitHub OAuth
app; change the port with --port if it registered a different one.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from ..engine import keys as eng_keys
from . import client


def _get_json(url: str, timeout: float = 15) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post_json(url: str, body: dict, timeout: float = 15) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.rstrip("/").endswith("callback"):
            self.send_response(404)
            self.end_headers()
            return
        _CallbackHandler.result = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        ok = "code" in _CallbackHandler.result
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Peakstone: linked \xe2\x9c\x93 you can close this tab.</h2>" if ok
                         else b"<h2>Peakstone: authorization failed \xe2\x80\x94 back to the terminal.</h2>")

    def log_message(self, *a):   # keep the CLI quiet
        pass


def _capture_code_loopback(authorize_url: str, port: int, timeout: float = 180) -> dict:
    """Open the browser, run a loopback server, and return the OAuth callback's query params."""
    srv = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    srv.timeout = 5
    _CallbackHandler.result = {}
    print(f"Opening GitHub in your browser… if it doesn't open, visit:\n  {authorize_url}\n")
    try:
        webbrowser.open(authorize_url)
    except Exception:  # noqa: BLE001 — headless: the printed URL still works
        pass
    deadline = time.monotonic() + timeout
    try:
        while not ({"code", "error"} & _CallbackHandler.result.keys()):
            if time.monotonic() > deadline:
                break
            srv.handle_request()   # blocks up to srv.timeout; a non-callback hit 404s and we loop
    finally:
        srv.server_close()
    return _CallbackHandler.result


def _extract_code(pasted: str) -> str:
    """Accept either a bare code or the full redirected URL the browser landed on."""
    pasted = pasted.strip()
    if "code=" in pasted:
        return urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).get("code", [""])[0] or pasted
    return pasted


def _looks_headless() -> bool:
    """No usable local browser for the loopback flow. Over SSH the browser + the 127.0.0.1 callback are
    on a DIFFERENT machine than this process, so the loopback server here never receives the redirect —
    paste-the-code mode is the only thing that works. Also true on a Linux box with no display."""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return True
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return True
    return False


def login_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="peakstone login",
                                 description="Link your signing key to a GitHub account")
    ap.add_argument("--api", default=client.API_DEFAULT, help="Peakstone API base URL")
    ap.add_argument("--provider", default="github")
    ap.add_argument("--port", type=int, default=53682,
                    help="loopback callback port (must match the server's registered OAuth callback)")
    ap.add_argument("--manual", action="store_true",
                    help="force paste-the-code mode (print the URL, paste the code back)")
    ap.add_argument("--browser", action="store_true",
                    help="force the loopback browser flow (override headless auto-detect)")
    args = ap.parse_args(argv)
    api = args.api.rstrip("/")
    # over SSH / no local browser, the loopback can't work (browser + callback are on another machine),
    # so default to paste-the-code there; --browser forces loopback, --manual forces paste.
    manual = args.manual or (not args.browser and _looks_headless())

    priv, pub = eng_keys.load_or_create_keypair()   # local root identity; created on first use

    # already linked? (404 = not bound yet, which is the normal path)
    try:
        who = _get_json(f"{api}/account?pubkey={urllib.parse.quote(pub, safe='')}")
        provs = ", ".join(p["provider"] for p in who.get("providers", []))
        print(f"Already linked as @{who.get('handle')} ({provs}). Nothing to do.")
        return 0
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"error checking account: {e}", file=sys.stderr)
            return 1
    except Exception as e:  # noqa: BLE001
        print(f"can't reach the API at {api}: {e}", file=sys.stderr)
        return 1

    redirect_uri = f"http://127.0.0.1:{args.port}/callback"
    state = secrets.token_urlsafe(16)
    try:
        au = _get_json(f"{api}/auth/{args.provider}/authorize-url?"
                       f"redirect_uri={urllib.parse.quote(redirect_uri, safe='')}&state={state}")
        authorize_url = au["authorize_url"]
    except Exception as e:  # noqa: BLE001
        print(f"couldn't get the authorize URL (is {args.provider} configured on the server?): {e}",
              file=sys.stderr)
        return 1

    if manual:
        if not args.manual:
            print("(no local browser detected — paste-the-code mode; pass --browser to force loopback)\n")
        print(f"1) Open this URL in a browser on ANY machine and authorize:\n\n  {authorize_url}\n\n"
              f"2) GitHub redirects to {redirect_uri} — that page won't load (it's a loopback on the\n"
              f"   machine you ran this from), but the address bar will contain '…?code=…'. Copy that\n"
              f"   whole URL (or just the code) and paste it here.")
        code = _extract_code(input("\nPaste it here: "))
    else:
        res = _capture_code_loopback(authorize_url, args.port)
        if res.get("state") != state:
            print("state mismatch — aborting (possible CSRF, or the callback timed out).", file=sys.stderr)
            return 1
        code = res.get("code")
        if not code:
            print(f"authorization failed: {res.get('error', 'no code returned')}", file=sys.stderr)
            return 1

    # prove key ownership by signing a fresh server nonce, then bind (both proofs together)
    try:
        nonce = _post_json(f"{api}/account/key-challenge", {"pubkey": pub})["nonce"]
        signature = eng_keys.sign(priv, nonce.encode())
        out = _post_json(f"{api}/account/bind", {
            "provider": args.provider, "pubkey": pub, "nonce": nonce,
            "signature": signature, "code": code, "redirect_uri": redirect_uri})
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        print(f"bind failed ({e.code}): {detail}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"bind failed: {e}", file=sys.stderr)
        return 1

    print(f"\n✓ linked as @{out.get('handle')} — your runs now show your handle and your "
          f"reproductions count toward community verification.")
    return 0

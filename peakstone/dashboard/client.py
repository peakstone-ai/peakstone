"""Peakstone API client for the dashboard — stdlib urllib (no extra deps).

Two services live here: the leaderboard API (submissions, board, runs) and the local model gateway
(`peakstone serve`) job-control endpoints. The dashboard is a thin client over both.
"""
from __future__ import annotations

import json
import lzma
import os
import urllib.error
import urllib.parse
import urllib.request

# Public instance by default — the dashboard ships to users via pipx and should point at the hosted
# leaderboard out of the box. The /api prefix matches Caddy's reverse-proxy route (handle_path /api/*
# -> api:8000). Override with PEAKSTONE_API_URL or --api to hit a local/self-hosted server.
API_DEFAULT = os.environ.get("PEAKSTONE_API_URL", "https://peakstone.ai/api")

# The local model gateway (peakstone serve). Loopback is auth-exempt, so the dashboard usually needs
# no token; PEAKSTONE_GATEWAY_TOKEN is sent as a bearer header when set (e.g. remote gateway).
# The base URL follows the [gateway] block in config.toml (via launch.load_gateway_config) so the
# client and daemon can't drift; PEAKSTONE_GATEWAY_URL overrides for a remote gateway.
def _gateway_default() -> str:
    if env := os.environ.get("PEAKSTONE_GATEWAY_URL"):
        return env
    try:
        from ..gateway.launch import base_url
        return base_url()
    except Exception:  # noqa: BLE001 — fall back if the gateway package isn't importable
        return "http://127.0.0.1:12434"


GATEWAY_DEFAULT = _gateway_default()
GATEWAY_TOKEN = os.environ.get("PEAKSTONE_GATEWAY_TOKEN", "")


class APIError(Exception):
    pass


def _get(base_url: str, path: str, params: dict, timeout: float) -> dict:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base_url.rstrip('/')}{path}" + (f"?{qs}" if qs else "")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise APIError(str(e))


def get_leaderboard(base_url: str, *, max_vram_gb: float | None = None,
                    sort: str = "code_score", collapse: str = "family", timeout: float = 10) -> dict:
    return _get(base_url, "/leaderboard",
                {"max_vram_gb": max_vram_gb, "sort": sort, "collapse": collapse}, timeout)


def get_facets(base_url: str, *, timeout: float = 10) -> dict:
    return _get(base_url, "/facets", {}, timeout)


def get_model(base_url: str, family: str, *, timeout: float = 10) -> dict:
    """All runs (no collapsing) for a family — the per-quant comparison data."""
    return _get(base_url, f"/models/{urllib.parse.quote(family, safe='')}", {}, timeout)


def get_account(base_url: str, pubkey: str, *, timeout: float = 5) -> dict | None:
    """The account bound to `pubkey` (handle + providers), or None if unbound / unreachable."""
    try:
        return _get(base_url, "/account", {"pubkey": pubkey}, timeout)
    except APIError:
        return None


def client_version() -> str:
    from ..engine import versions
    return versions.pkg_version()


def get_version(base_url: str, *, timeout: float = 5) -> dict | None:
    """The server's client-version policy {latest, min_supported, api}, or None if unreachable."""
    try:
        return _get(base_url, "/version", {}, timeout)
    except APIError:
        return None


def get_run(base_url: str, bundle_hash: str, *, timeout: float = 10) -> dict:
    """Per-challenge results for one run (lite: scores + error type, no transcripts)."""
    return _get(base_url, f"/runs/{urllib.parse.quote(bundle_hash, safe='')}", {}, timeout)


def get_run_challenge(base_url: str, bundle_hash: str, challenge_id: str, *, timeout: float = 10) -> dict:
    """One challenge's full result incl. transcript (fetched on solution-open)."""
    return _get(base_url, f"/runs/{urllib.parse.quote(bundle_hash, safe='')}"
                f"/challenge/{urllib.parse.quote(challenge_id, safe='')}", {}, timeout)


def submit_bundle(base_url: str, bundle: dict, *, timeout: float = 30) -> tuple[int, str]:
    """POST a signed result bundle. Returns (http_status, detail); 201 ok, 409 already submitted,
    400 rejected. Raises APIError only if the server is unreachable."""
    # Bundles are large, transcript-heavy JSON → compress the upload to cut bandwidth (we compress
    # ONCE on expensively-generated data, so spend the CPU). xz/lzma beats gzip by ~25-30% here
    # (~6.5-8x) and decompresses fast; the server also accepts gzip and uncompressed (backward-compat).
    body = lzma.compress(json.dumps(bundle).encode())
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/submissions", data=body,
        headers={"content-type": "application/json", "content-encoding": "xz",
                 "x-peakstone-client": client_version()},   # lets the server refuse too-old clients
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except (urllib.error.URLError, OSError) as e:
        raise APIError(str(e))


# --- model gateway: job control ----------------------------------------------------------------

def _gw_headers() -> dict:
    h = {"content-type": "application/json"}
    if GATEWAY_TOKEN:
        h["authorization"] = f"Bearer {GATEWAY_TOKEN}"
    return h


def _gw_request(method: str, base_url: str, path: str, body: dict | None = None,
                *, timeout: float = 10) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data,
                                 headers=_gw_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"detail": raw[:200]}
    except (urllib.error.URLError, OSError) as e:
        raise APIError(str(e))


def enqueue_job(spec: dict, *, kind: str = "run", base_url: str = GATEWAY_DEFAULT,
                timeout: float = 10) -> str:
    """Queue a job on the gateway; returns the job id. kind="run" (benchmark; spec keys: model,
    level|ids, ctx, reasoning, budget) or kind="download" (spec: just model). A run for a model that
    isn't on disk auto-queues its download on the daemon side."""
    status, body = _gw_request("POST", base_url, "/jobs", {**spec, "kind": kind}, timeout=timeout)
    if status != 201:
        raise APIError(f"enqueue failed ({status}): {body.get('detail', body)}")
    return body["id"]


def download_model(model: str, *, base_url: str = GATEWAY_DEFAULT, timeout: float = 10) -> str:
    """Queue a model download on the daemon's (separate, concurrent) download queue. Returns job id."""
    return enqueue_job({"model": model}, kind="download", base_url=base_url, timeout=timeout)


def list_jobs(*, base_url: str = GATEWAY_DEFAULT, timeout: float = 10) -> list[dict]:
    return _gw_request("GET", base_url, "/jobs", timeout=timeout)[1].get("jobs", [])


def get_job(jid: str, *, base_url: str = GATEWAY_DEFAULT, timeout: float = 10) -> dict | None:
    status, body = _gw_request("GET", base_url, f"/jobs/{jid}", timeout=timeout)
    return body if status == 200 else None


def get_job_bundle(jid: str, *, base_url: str = GATEWAY_DEFAULT, timeout: float = 30) -> dict | None:
    """A finished job's signed bundle, over HTTP — works against a REMOTE daemon too (the TUI used
    to read it off the daemon's local disk, which silently broke off-host — review R21)."""
    status, body = _gw_request("GET", base_url, f"/jobs/{jid}/bundle", timeout=timeout)
    return body if status == 200 else None


def cancel_job(jid: str, *, base_url: str = GATEWAY_DEFAULT, timeout: float = 10) -> bool:
    return _gw_request("DELETE", base_url, f"/jobs/{jid}", timeout=timeout)[0] == 200


def pause_job(jid: str, *, base_url: str = GATEWAY_DEFAULT, timeout: float = 10) -> bool:
    """Pause a queued or running job (running → stopped + re-runnable). The scheduler skips ahead."""
    return _gw_request("POST", base_url, f"/jobs/{jid}/pause", {}, timeout=timeout)[0] == 200


def resume_job(jid: str, *, base_url: str = GATEWAY_DEFAULT, timeout: float = 10) -> bool:
    """Resume a paused job → back on the queue (re-runs, reloading its model when picked)."""
    return _gw_request("POST", base_url, f"/jobs/{jid}/resume", {}, timeout=timeout)[0] == 200


def unload_model(*, base_url: str = GATEWAY_DEFAULT, timeout: float = 30) -> tuple[bool, str]:
    """Free VRAM by unloading the gateway's loaded model. Returns (ok, detail); ok=False if a run holds
    the GPU (409) or nothing was loaded."""
    status, body = _gw_request("POST", base_url, "/unload", {}, timeout=timeout)
    if status == 200:
        return True, ("unloaded" if body.get("unloaded") else "no model was loaded")
    return False, str(body.get("detail", body))


def stream_job_log(jid: str, *, base_url: str = GATEWAY_DEFAULT, timeout: float = 600):
    """Yield a job's log lines (SSE `data:` payloads) until the run finishes or the connection drops.
    Disconnecting does NOT affect the run — it lives in the daemon."""
    req = urllib.request.Request(f"{base_url.rstrip('/')}/jobs/{jid}/log", headers=_gw_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload and payload != "{}":
                        yield payload
    except (urllib.error.URLError, OSError) as e:
        raise APIError(str(e))

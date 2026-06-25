"""Peakstone API client for the dashboard — stdlib urllib (no extra deps)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API_DEFAULT = os.environ.get("PEAKSTONE_API_URL", "http://localhost:8000")


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
                    sort: str = "code_score", timeout: float = 10) -> dict:
    return _get(base_url, "/leaderboard", {"max_vram_gb": max_vram_gb, "sort": sort}, timeout)


def get_facets(base_url: str, *, timeout: float = 10) -> dict:
    return _get(base_url, "/facets", {}, timeout)


def get_model(base_url: str, family: str, *, timeout: float = 10) -> dict:
    """All runs (no collapsing) for a family — the per-quant comparison data."""
    return _get(base_url, f"/models/{urllib.parse.quote(family, safe='')}", {}, timeout)


def submit_bundle(base_url: str, bundle: dict, *, timeout: float = 30) -> tuple[int, str]:
    """POST a signed result bundle. Returns (http_status, detail); 201 ok, 409 already submitted,
    400 rejected. Raises APIError only if the server is unreachable."""
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/submissions", data=json.dumps(bundle).encode(),
        headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except (urllib.error.URLError, OSError) as e:
        raise APIError(str(e))

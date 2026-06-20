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

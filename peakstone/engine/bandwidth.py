"""Rolling download-throughput estimate, fed from real transfers (model downloads, image pulls), so
run-time estimates can account for bandwidth. Stored at ~/.peakstone/bandwidth.json.

MB/s uses MB = 1e6 bytes. Convert: download_minutes = (bytes/1e9)*1000 / mbps / 60.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from pathlib import Path

from . import keys

PATH = keys.KEY_DIR / "bandwidth.json"
_MAX = 20


def _load(path: Path | None = None) -> list:
    try:
        d = json.loads((path or PATH).read_text())
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def record(num_bytes, seconds, source: str = "", path: Path | None = None) -> None:
    """Append a throughput sample (no-op for missing/degenerate inputs)."""
    if not num_bytes or not seconds or seconds <= 0:
        return
    p = path or PATH
    samples = _load(p)
    samples.append({"mbps": round(num_bytes / 1e6 / seconds, 2), "bytes": int(num_bytes),
                    "source": source,
                    "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    samples = samples[-_MAX:]
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(samples, indent=2))
    tmp.replace(p)


def estimated_mbps(path: Path | None = None) -> float | None:
    """Median of recent throughput samples (MB/s), or None if we have no data yet."""
    vals = [x["mbps"] for x in _load(path) if isinstance(x.get("mbps"), (int, float))]
    return round(statistics.median(vals), 1) if vals else None

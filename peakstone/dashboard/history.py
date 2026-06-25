"""Per-run reproduce history — a small JSON log under PEAKSTONE_HOME (~/.peakstone)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("PEAKSTONE_HOME", Path.home() / ".peakstone"))
HISTORY_PATH = HOME / "repro-history.json"


def load() -> list[dict]:
    try:
        data = json.loads(HISTORY_PATH.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def append(entry: dict) -> None:
    hist = load()
    hist.append({"at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), **entry})
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(hist, indent=2))
    tmp.replace(HISTORY_PATH)   # atomic

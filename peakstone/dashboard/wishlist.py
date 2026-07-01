"""Personal model wishlist — a local, per-machine list of models you want to test, with one-key
download from the TUI. Stored at ``$PEAKSTONE_HOME/wishlist.json`` (untracked). A bootstrapping aid
(no server, no auth): your own queue of models to pull + benchmark, so the dashboard is immediately
useful even before the leaderboard fills in.

Each entry: ``{"name": ..., "repo": ..., "note": ...}`` — name is a local model id, repo is the HF
repo to download from (opens the quant browser), note is a free-text reason/priority.
"""
from __future__ import annotations

import json

from peakstone.engine import paths


def _path():
    return paths.home_dir() / "wishlist.json"


def load() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def save(items: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2))
    tmp.replace(p)


def add(name: str, repo: str = "", note: str = "") -> list[dict]:
    name = name.strip()
    items = load()
    if name and not any(i.get("name") == name for i in items):
        items.append({"name": name, "repo": repo.strip(), "note": note.strip()})
        save(items)
    return items


def remove(name: str) -> list[dict]:
    items = [i for i in load() if i.get("name") != name]
    save(items)
    return items

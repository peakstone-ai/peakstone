"""Tiny dotted-version comparison (no `packaging` dependency) for client/server compatibility checks."""
from __future__ import annotations

import itertools


def version_key(v: str | None) -> tuple:
    """Sortable key from a version like '0.2.0'. Each dotted part contributes its LEADING digits (so a
    pre-release/build suffix like '0rc1' -> 0); good enough for X.Y.Z compatibility gating."""
    out = []
    for part in (v or "0").split("."):
        digits = "".join(itertools.takewhile(str.isdigit, part))
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_outdated(installed: str | None, minimum: str | None) -> bool:
    """True iff `installed` is strictly older than `minimum`."""
    return version_key(installed) < version_key(minimum)


def pkg_version() -> str:
    """The installed peakstone package version (or '0.0.0' if it can't be determined)."""
    try:
        from importlib.metadata import version
        return version("peakstone")
    except Exception:  # noqa: BLE001
        return "0.0.0"

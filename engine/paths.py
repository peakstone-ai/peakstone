"""Centralized data-path resolution.

The package runs in two situations and these helpers make both work:

* **In-repo** — an editable install, a git checkout, or the Docker image. Everything is on disk
  next to the package; the challenge corpus and serve helpers live at the repo root.
* **Installed wheel** (PyPI) — only the package's own files exist. The corpus and serve scripts
  are *not* shipped (running the suite needs a checkout anyway: reference solutions, the JS
  sandbox's `node_modules`, `serve.sh`, llama-server, GGUF weights).

Two kinds of data, resolved differently:

* **Packaged data** — travels inside the `engine` package, so it is always present: the result-bundle
  JSON Schema (`engine/schema/`) and the run config (`engine/config.toml`). Producing/validating a
  bundle works from a bare `pip install`.
* **Repo data** — the benchmark workspace: `challenges/` and `serve/`. Found at the repo root when
  in-repo, or wherever ``PEAKSTONE_REPO`` points. Requesting it without a checkout raises a clear,
  actionable error rather than a cryptic ``FileNotFoundError``.

Override precedence (highest first): a resource-specific env var, then ``PEAKSTONE_REPO``, then the
in-repo location relative to this file.
"""
from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent     # .../engine  (real path for editable + normal wheels)
_REPO_DEFAULT = _PKG.parent                # repo root when running in-repo


class DataNotFound(RuntimeError):
    """A required repo data directory (challenges/, serve/) is missing — see the message."""


# --- packaged data (always shipped in the wheel) ------------------------------------------------

def schema_path() -> Path:
    """The result-bundle JSON Schema (the reproducibility contract)."""
    return Path(os.environ.get("PEAKSTONE_SCHEMA") or _PKG / "schema" / "result-bundle.schema.json")


def taxonomy_path() -> Path:
    """The capability taxonomy."""
    return Path(os.environ.get("PEAKSTONE_TAXONOMY") or _PKG / "schema" / "taxonomy.json")


def config_path() -> Path:
    """The engine run config (engine/config.toml)."""
    return Path(os.environ.get("PEAKSTONE_CONFIG") or _PKG / "config.toml")


# --- repo data (the benchmark workspace; needs a checkout) --------------------------------------

def repo_root() -> Path:
    """The benchmark repo root: ``$PEAKSTONE_REPO``, else the in-repo parent of this package."""
    return Path(os.environ.get("PEAKSTONE_REPO", _REPO_DEFAULT))


def _repo_dir(name: str, env: str) -> Path:
    return Path(os.environ[env]) if os.environ.get(env) else repo_root() / name


def challenges_dir() -> Path:
    """The challenge corpus root (override: ``PEAKSTONE_CHALLENGES``)."""
    return _repo_dir("challenges", "PEAKSTONE_CHALLENGES")


def serve_dir() -> Path:
    """The serving helpers dir (override: ``PEAKSTONE_SERVE``)."""
    return _repo_dir("serve", "PEAKSTONE_SERVE")


def models_toml() -> Path:
    """The local model registry, ``serve/models.toml`` (override: ``PEAKSTONE_MODELS_TOML``)."""
    env = os.environ.get("PEAKSTONE_MODELS_TOML")
    return Path(env) if env else serve_dir() / "models.toml"


def require(path: Path, what: str) -> Path:
    """Return ``path`` if it exists, else raise :class:`DataNotFound` pointing at the fix."""
    if path.exists():
        return path
    raise DataNotFound(
        f"{what} not found at {path}. Running the benchmark suite needs a repo checkout — "
        f"`git clone` it and set PEAKSTONE_REPO=<checkout> (or pass an explicit path). "
        f"The PyPI package ships the dashboard + engine library, not the challenge corpus."
    )

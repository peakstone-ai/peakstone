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

_PKG = Path(__file__).resolve().parent     # .../peakstone/engine  (real path for editable + wheels)
_REPO_DEFAULT = _PKG.parents[1]            # repo root when running in-repo (peakstone/ -> repo)


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


def home_dir() -> Path:
    """Per-machine Peakstone home: ``$PEAKSTONE_HOME`` (default ~/.peakstone). Holds the signing keys,
    the config override, and the GitHub-synced challenge corpus for pip-installed clients."""
    return Path(os.environ.get("PEAKSTONE_HOME", str(Path.home() / ".peakstone")))


def user_config_path() -> Path:
    """Per-machine config override at ``$PEAKSTONE_HOME/config.toml`` (default ~/.peakstone/config.toml).
    Untracked; its sections overlay the committed engine/config.toml so a machine can opt into local
    settings (e.g. [gateway] host/open for LAN exposure) without editing the repo."""
    return home_dir() / "config.toml"


def load_config() -> dict:
    """The engine config with the per-machine override applied: engine/config.toml overlaid
    section-wise by ~/.peakstone/config.toml (overlay keys win). This is the SAME override rule
    the gateway and API already honor — the engine used to read only the packaged file, so a
    user's [run]/[judge] override changed the daemon's behavior but silently not the runner's
    (review R31)."""
    import tomllib
    cfg: dict = {}
    for p in (config_path(), user_config_path()):
        try:
            for section, block in tomllib.loads(p.read_text()).items():
                if isinstance(block, dict):
                    cfg.setdefault(section, {}).update(block)
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return cfg


def locked(path: Path):
    """An exclusive advisory lock (fcntl) scoped to `path` — serializes read-modify-write of the
    small JSON caches so concurrent runs can't drop each other's entries (review R31: atomic
    rename made writes non-corrupting, but last-writer-wins still lost merges)."""
    import fcntl
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        lock = path.with_name(path.name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    return _cm()


# --- repo data (the benchmark workspace; needs a checkout) --------------------------------------

def repo_root() -> Path:
    """The benchmark repo root: ``$PEAKSTONE_REPO``, else the in-repo parent of this package."""
    return Path(os.environ.get("PEAKSTONE_REPO", _REPO_DEFAULT))


def _repo_dir(name: str, env: str) -> Path:
    return Path(os.environ[env]) if os.environ.get(env) else repo_root() / name


def challenges_dir() -> Path:
    """The challenge corpus root. Override: ``PEAKSTONE_CHALLENGES``. In a repo checkout it's
    ``<repo>/challenges``; for a pip-installed client with no checkout it falls back to the corpus
    synced from GitHub into ``$PEAKSTONE_HOME/challenges`` (populate it with ``peakstone corpus sync``)."""
    env = os.environ.get("PEAKSTONE_CHALLENGES")
    if env:
        return Path(env)
    repo = repo_root() / "challenges"
    if repo.exists():
        return repo
    return home_dir() / "challenges"


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
        f"{what} not found at {path}. For a pip-installed client, fetch the challenge corpus with "
        f"`peakstone corpus sync`. In a repo checkout, run from the checkout or set "
        f"PEAKSTONE_REPO=<checkout>. (serve/ helpers + weights still need a checkout.)"
    )

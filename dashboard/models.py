"""Local model registry + downloads for the dashboard.

The registry is serve/models.toml (name -> repo/file/port/ctx/flags), the same file serve/serve.sh
reads. GGUFs live under models/<name>/. This module lists what's registered + present, adds new
entries, and downloads files via the `hf` CLI.
"""
from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

# repo root (editable install): dashboard/ is a sibling of serve/ and models/. Override for other layouts.
REPO = Path(os.environ.get("PEAKSTONE_REPO", Path(__file__).resolve().parents[1]))
MODELS_TOML = REPO / "serve" / "models.toml"


@dataclass
class ModelEntry:
    name: str
    repo: str | None
    file: str | None
    port: int | None
    ctx: int | None
    flags: str = ""

    @property
    def path(self) -> Path | None:
        return (REPO / self.file) if self.file else None

    @property
    def present(self) -> bool:
        p = self.path
        return bool(p and p.exists())

    @property
    def size_gb(self) -> float | None:
        p = self.path
        return round(p.stat().st_size / 1e9, 1) if (p and p.exists()) else None


def load_registry() -> dict[str, ModelEntry]:
    if not MODELS_TOML.exists():
        return {}
    data = tomllib.loads(MODELS_TOML.read_text())
    return {n: ModelEntry(n, m.get("repo"), m.get("file"), m.get("port"), m.get("ctx"),
                          m.get("flags", "")) for n, m in data.items()}


def _next_port(reg: dict[str, ModelEntry]) -> int:
    ports = [e.port for e in reg.values() if isinstance(e.port, int)]
    return (max(ports) + 1) if ports else 8081


def add_model(name: str, repo: str, file: str | None = None, *, port: int | None = None,
              ctx: int = 32768, flags: str = "") -> ModelEntry:
    """Append a model to the registry. `file` defaults to models/<name>/<basename-of-repo-file>;
    pass the HF filename as `file` (just the basename) to set where it downloads."""
    if not name or not name.replace("-", "").replace(".", "").replace("_", "").isalnum():
        raise ValueError("model name must be alphanumeric (with -._)")
    reg = load_registry()
    if name in reg:
        raise ValueError(f"model {name!r} already registered")
    basename = Path(file).name if file else f"{name}.gguf"
    rel = f"models/{name}/{basename}"
    port = port or _next_port(reg)
    block = (f'\n["{name}"]\nrepo  = "{repo}"\nfile  = "{rel}"\nport  = {port}\n'
             f'ctx   = {ctx}\nflags = "{flags}"\n')
    MODELS_TOML.parent.mkdir(parents=True, exist_ok=True)
    with open(MODELS_TOML, "a") as f:
        f.write(block)
    return ModelEntry(name, repo, rel, port, ctx, flags)


def download(entry: ModelEntry, log=lambda s: None, *, runner=subprocess.run) -> bool:
    """Fetch the GGUF via `hf download <repo> <filename> --local-dir models/<name>`. Returns True on
    success. `runner` is injectable for tests."""
    if not entry.repo or not entry.file:
        log("no repo/file in registry for this model")
        return False
    if entry.present:
        log(f"{entry.name} already present ({entry.size_gb} GB)")
        return True
    local_dir = REPO / "models" / entry.name
    filename = Path(entry.file).name
    log(f"downloading {entry.repo} / {filename} → {local_dir} …")
    env = {**os.environ, "HF_HUB_ENABLE_HF_TRANSFER": "1"}
    r = runner(["hf", "download", entry.repo, filename, "--local-dir", str(local_dir)],
               env=env, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"download failed: {(r.stderr or '')[-300:]}")
        return False
    log(f"downloaded {entry.name} ({entry.size_gb} GB)")
    return entry.present

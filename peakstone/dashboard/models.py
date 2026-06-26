"""Local model registry + downloads for the dashboard.

The registry is serve/models.toml (name -> repo/file/port/ctx/flags), the same file serve/serve.sh
reads. GGUFs live under models/<name>/. This module lists what's registered + present, adds new
entries, and downloads files via the `hf` CLI.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from peakstone.engine import bandwidth, paths

# Both the registry and the GGUF store live in the repo workspace. engine.paths is the single
# resolver (honours PEAKSTONE_REPO / PEAKSTONE_MODELS_TOML); reproduce/serve need a checkout anyway.
REPO = paths.repo_root()
MODELS_TOML = paths.models_toml()

# Cache of HF-discovered quant listings, so the models screen doesn't re-hit the API every open.
HF_QUANTS_CACHE = Path.home() / ".peakstone" / "hf_quants.json"

_QUANT_RE = re.compile(r"(UD-)?((?:IQ|Q)\d+(?:_[A-Za-z0-9]+)*|BF16|F16|F32)", re.I)


def quant_label(filename: str | None) -> str:
    """The quant tag from a GGUF filename, e.g. 'Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf' -> 'UD-Q4_K_XL',
    'Phi-4-mini-instruct-Q6_K.gguf' -> 'Q6_K'. '?' when no quant token is present."""
    if not filename:
        return "?"
    m = _QUANT_RE.search(Path(filename).name)
    if not m:
        return "?"
    return (m.group(1) or "").upper() + m.group(2).upper()


@dataclass
class ModelEntry:
    name: str
    repo: str | None
    file: str | None
    port: int | None
    ctx: int | None
    flags: str = ""
    family: str = ""

    @property
    def fam(self) -> str:
        """Grouping key for the models menu: the explicit `family` key, else the model name (so a
        lone entry is just a one-quant family)."""
        return self.family or self.name

    @property
    def quant(self) -> str:
        """Quant tag parsed from the GGUF filename (e.g. 'UD-Q4_K_XL')."""
        return quant_label(self.file)

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
                          m.get("flags", ""), m.get("family", "")) for n, m in data.items()}


def group_by_family(registry: dict[str, ModelEntry]) -> dict[str, list[ModelEntry]]:
    """{family: registered quant entries}, families alphabetical, quants by label within."""
    out: dict[str, list[ModelEntry]] = defaultdict(list)
    for e in registry.values():
        out[e.fam].append(e)
    for v in out.values():
        v.sort(key=lambda e: e.quant)
    return dict(sorted(out.items()))


def available_quants(repo: str, *, refresh: bool = False, cache_path: Path | None = None) -> list[dict]:
    """GGUF quants offered by an HF repo: [{quant, file, size_gb}], largest-quant-ish order. Cached to
    disk (keyed by repo) so the menu is instant after the first lookup; best-effort — returns [] if HF
    is unreachable or huggingface_hub is missing. Split GGUFs (00001-of-000NN) collapse to one quant."""
    cache_path = cache_path or HF_QUANTS_CACHE
    cache: dict = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:  # noqa: BLE001
            cache = {}
    if not refresh and repo in cache:
        return cache[repo]
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(repo, files_metadata=True)
    except Exception:  # noqa: BLE001 — offline / missing dep / bad repo: caller falls back to registry
        return cache.get(repo, [])
    sizes: dict[str, int] = defaultdict(int)
    firstfile: dict[str, str] = {}
    for s in info.siblings or []:
        if not s.rfilename.endswith(".gguf"):
            continue
        q = quant_label(s.rfilename)
        sizes[q] += s.size or 0
        firstfile.setdefault(q, s.rfilename)
    quants = [{"quant": q, "file": firstfile[q], "size_gb": round(sizes[q] / 1e9, 1) or None}
              for q in sorted(sizes)]
    cache[repo] = quants
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2))
    except Exception:  # noqa: BLE001
        pass
    return quants


def _next_port(reg: dict[str, ModelEntry]) -> int:
    ports = [e.port for e in reg.values() if isinstance(e.port, int)]
    return (max(ports) + 1) if ports else 8081


def add_model(name: str, repo: str, file: str | None = None, *, port: int | None = None,
              ctx: int = 32768, flags: str = "", family: str = "") -> ModelEntry:
    """Append a model to the registry. `file` defaults to models/<name>/<basename-of-repo-file>;
    pass the HF filename as `file` (just the basename) to set where it downloads. `family` groups
    quant variants together in the models menu."""
    if not name or not name.replace("-", "").replace(".", "").replace("_", "").isalnum():
        raise ValueError("model name must be alphanumeric (with -._)")
    reg = load_registry()
    if name in reg:
        raise ValueError(f"model {name!r} already registered")
    basename = Path(file).name if file else f"{name}.gguf"
    rel = f"models/{name}/{basename}"
    port = port or _next_port(reg)
    fam_line = f'family = "{family}"\n' if family else ""
    block = (f'\n["{name}"]\nrepo  = "{repo}"\nfile  = "{rel}"\nport  = {port}\n'
             f'ctx   = {ctx}\nflags = "{flags}"\n{fam_line}')
    MODELS_TOML.parent.mkdir(parents=True, exist_ok=True)
    with open(MODELS_TOML, "a") as f:
        f.write(block)
    return ModelEntry(name, repo, rel, port, ctx, flags, family)


def register_quant(family: str, repo: str, file: str, quant: str) -> ModelEntry:
    """Register an HF-discovered quant under a family so it can be downloaded + run. Derives a unique
    registry name from family+quant; returns the existing entry if that file is already registered."""
    reg = load_registry()
    for e in reg.values():
        if e.repo == repo and e.file and Path(e.file).name == Path(file).name:
            return e
    name = f"{family}-{quant.lower().replace('ud-', '')}"
    suffix, base = 0, name
    while name in reg:
        suffix += 1
        name = f"{base}-{suffix}"
    return add_model(name, repo, file=file, family=family)


def remote_size(repo: str, filename: str) -> int | None:
    """Total bytes of a repo file (for a real progress bar), via the HF API. Best-effort."""
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url
        return get_hf_file_metadata(hf_hub_url(repo, filename)).size
    except Exception:  # noqa: BLE001  (network/auth/version — fall back to indeterminate)
        return None


def _dir_size(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) if d.exists() else 0


class _Cancelled(Exception):
    """Raised from the progress tap to abort an in-flight hf_hub_download."""


def _hf_fetch(repo: str, filename: str, local_dir: str, *, progress, cancel, log) -> None:
    """Download one file via huggingface_hub (keeps Xet acceleration, stored credentials, redirect
    handling and resume), tapping its tqdm progress bar so we get byte-accurate updates. Both the
    HTTP and Xet backends route progress through huggingface_hub.utils.tqdm.tqdm, so subclassing it
    and forwarding update() captures progress regardless of backend. cancel() aborts via _Cancelled."""
    import importlib
    from huggingface_hub import hf_hub_download
    tqmod = importlib.import_module("huggingface_hub.utils.tqdm")   # the submodule (shadowed by the class)
    orig = tqmod.tqdm

    class _Tap(orig):
        def update(self, n=1):
            r = super().update(n)
            if self.n is not None and progress is not None:
                progress(self.n, self.total or None)
            if cancel and cancel():
                raise _Cancelled()
            return r

    tqmod.tqdm = _Tap
    try:
        hf_hub_download(repo, filename, local_dir=local_dir)
    finally:
        tqmod.tqdm = orig


def download(entry: ModelEntry, log=lambda s: None, *, progress=None, cancel=None,
             on_proc=None, _fetch=_hf_fetch) -> bool:
    """Fetch the GGUF via huggingface_hub (Xet + credentials + resume), reporting byte progress by
    tapping its progress bar — the `hf` CLI's xet backend buffers in a separate cache and only
    materializes the file at the end, so polling the output dir shows no progress. `progress(done,
    total)` fires as bytes arrive; `cancel()` aborts; `_fetch` is injectable for tests."""
    if not entry.repo or not entry.file:
        log("no repo/file in registry for this model")
        return False
    if entry.present:
        log(f"{entry.name} already present ({entry.size_gb} GB)")
        return True
    local_dir = REPO / "models" / entry.name
    local_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(entry.file).name
    log(f"downloading {entry.repo} / {filename} → {local_dir} …")
    if progress is not None:                          # show the right size immediately — the xet backend
        progress(0, remote_size(entry.repo, filename))   # has a quiet startup before the first byte
    t0 = time.monotonic()
    try:
        _fetch(entry.repo, filename, str(local_dir), progress=progress, cancel=cancel, log=log)
    except _Cancelled:
        log("download cancelled")
        return False
    except Exception as e:  # noqa: BLE001  (network/auth/missing file)
        log(f"download failed: {e}")
        return False
    elapsed = time.monotonic() - t0
    if elapsed > 0 and entry.present and entry.path:
        bandwidth.record(entry.path.stat().st_size, elapsed, "hf")   # calibrate run estimates
    log(f"downloaded {entry.name} ({entry.size_gb} GB)")
    return entry.present

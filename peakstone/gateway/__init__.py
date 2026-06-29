"""peakstoned — a standing, llama-swap-style OpenAI gateway over the local model registry.

One process exposes a single OpenAI-compatible endpoint (default :11434). Each request names a model;
the gateway ensures that model is the one loaded on the GPU (starting/swapping the backing
llama-server on demand) and reverse-proxies the request through. When not running benchmarks it is
simply a local OpenAI endpoint for any client (the `openai` SDK, Open WebUI, editors, …).

Public surface:
- `ModelManager` (swap.py) — the on-demand load/swap state machine.
- `build_app()` / `run()` (app.py) — the FastAPI app and its uvicorn entrypoint.
"""
from __future__ import annotations

from .app import build_app, run
from .swap import Busy, ModelManager, ServeFailed, UnknownModel

__all__ = ["Busy", "ModelManager", "ServeFailed", "UnknownModel", "build_app", "run"]

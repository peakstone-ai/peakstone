"""On-demand model load/swap — the llama-swap state machine behind the gateway.

Only one model fits in VRAM at a time (the existing reality of this lab), so the manager keeps at
most one backing llama-server alive and swaps it when a request names a different model. A swap
*drains* in-flight requests on the current model first, stops it (frees VRAM), starts the requested
one, and waits for it to become healthy.

Concurrency (all on one asyncio event loop):
- A `lease(model)` holds an `asyncio.Lock` only for the load-check + in-flight registration, then
  releases it for the duration of the proxied request — so many requests for the *same* loaded model
  run concurrently, while a request for a *different* model serializes behind the swap.
- A swap holds that same lock across the whole stop→start→health cycle, so new requests queue behind
  it. It waits for the in-flight counter (decremented lock-free as requests finish) to reach zero
  before tearing the current server down — no request is cut off mid-generation.

The blocking primitives (serve / wait_healthy / stop) come from `engine.serving` and are run in a
thread (`asyncio.to_thread`) so they never block the loop; they're injectable so tests need no GPU.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from ..engine import serving
from ..engine.serving import ServeModel


class UnknownModel(KeyError):
    """Requested a model that isn't in serve/models.toml."""


class ServeFailed(RuntimeError):
    """The backing llama-server didn't come up healthy (OOM, missing GGUF, bad flags…)."""

    def __init__(self, name: str, log_tail: str = ""):
        self.name = name
        self.log_tail = log_tail
        super().__init__(f"llama-server for {name!r} failed to become healthy"
                         + (f":\n{log_tail}" if log_tail else ""))


class Busy(RuntimeError):
    """A benchmark job has pinned the GPU to one model; a request for a different model is refused
    rather than thrashing the run. Maps to HTTP 503."""

    def __init__(self, pinned: str, requested: str):
        self.pinned = pinned
        self.requested = requested
        super().__init__(f"busy benchmarking {pinned!r}; {requested!r} unavailable until it finishes")


class ModelManager:
    """Keeps at most one llama-server loaded; swaps it to satisfy the requested model."""

    def __init__(self, *, idle_timeout: float = 0.0, registry: dict[str, ServeModel] | None = None,
                 _serve=serving.serve, _wait=serving.wait_healthy, _stop=serving.stop,
                 _registry_loader=serving.load_registry, _log_tail=serving.serve_log_tail,
                 _clock=time.monotonic):
        # idle_timeout > 0 unloads the model after that many idle seconds (frees VRAM); 0 = never.
        self._idle_timeout = idle_timeout
        self._registry_override = registry
        self._serve, self._wait, self._stop = _serve, _wait, _stop
        self._registry_loader, self._log_tail, self._clock = _registry_loader, _log_tail, _clock

        self.current: str | None = None          # currently-loaded model name
        self.proc = None                          # its serve subprocess (Popen-like)
        self.last_swap: dict | None = None        # {"from", "to"} of the most recent swap, for /status
        self.pinned: str | None = None            # while a benchmark job runs, the GPU is pinned here

        self._lock = asyncio.Lock()               # guards load-check + swap + in-flight registration
        self._inflight = 0                        # proxied requests currently using the loaded model
        self._drained = asyncio.Event()
        self._drained.set()                       # set whenever in-flight == 0
        self._last_activity = self._clock()
        self._idle_task: asyncio.Task | None = None

    # --- registry -------------------------------------------------------------------------------

    def registry(self) -> dict[str, ServeModel]:
        return self._registry_override if self._registry_override is not None else self._registry_loader()

    def model(self, name: str) -> ServeModel | None:
        return self.registry().get(name)

    # --- lifecycle ------------------------------------------------------------------------------

    def start(self) -> None:
        """Start the idle-unload watcher (no-op if idle unloading is disabled)."""
        if self._idle_timeout > 0 and self._idle_task is None:
            self._idle_task = asyncio.create_task(self._idle_loop())

    async def aclose(self) -> None:
        """Stop the idle watcher and tear down the loaded model (called on daemon shutdown)."""
        if self._idle_task is not None:
            self._idle_task.cancel()
            try:
                await self._idle_task
            except asyncio.CancelledError:
                pass
            self._idle_task = None
        if self._alive():
            await asyncio.to_thread(self._stop, self.proc)
        self.current, self.proc = None, None

    # --- state ----------------------------------------------------------------------------------

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def status(self) -> dict:
        return {
            "current": self.current,
            "alive": self._alive(),
            "pinned": self.pinned,
            "inflight": self._inflight,
            "idle_timeout_s": self._idle_timeout,
            "idle_for_s": round(self._clock() - self._last_activity, 1) if self.current else None,
            "last_swap": self.last_swap,
            "models": sorted(self.registry()),
        }

    # --- load / swap ----------------------------------------------------------------------------

    async def _wait_drained(self) -> None:
        """Block until no requests are using the current model (so it's safe to tear down)."""
        while self._inflight > 0:
            self._drained.clear()
            await self._drained.wait()

    async def _ensure_locked(self, name: str) -> ServeModel:
        """Bring `name` up as the loaded model. Caller MUST hold `self._lock`."""
        m = self.model(name)
        if m is None:
            raise UnknownModel(name)
        if self.pinned is not None and self.pinned != name:
            raise Busy(self.pinned, name)         # a job owns the GPU; don't swap out from under it
        if self.current == name and self._alive():
            return m                              # already loaded and healthy — nothing to do
        await self._wait_drained()                # let in-flight work on the old model finish
        if self._alive():
            await asyncio.to_thread(self._stop, self.proc)
        prev, self.current, self.proc = self.current, None, None
        proc = await asyncio.to_thread(self._serve, name)
        healthy = await asyncio.to_thread(self._wait, m.port, proc=proc)
        if not healthy:
            await asyncio.to_thread(self._stop, proc)
            raise ServeFailed(name, self._log_tail(name))
        self.proc, self.current = proc, name
        self.last_swap = {"from": prev, "to": name}
        return m

    async def ensure_loaded(self, name: str) -> ServeModel:
        """Ensure `name` is the loaded model (swapping if needed). Standalone helper / warm-up."""
        if self.current == name and self._alive():
            return self.model(name)
        async with self._lock:
            return await self._ensure_locked(name)

    async def pin(self, name: str) -> ServeModel:
        """Reserve the GPU for `name` (a running benchmark): load it now and reject swaps to any other
        model until unpin(). Raises UnknownModel/ServeFailed if it can't be loaded."""
        async with self._lock:
            self.pinned = name
            try:
                return await self._ensure_locked(name)
            except BaseException:
                self.pinned = None
                raise

    def unpin(self) -> None:
        """Release the GPU pin (the model stays loaded for reuse)."""
        self.pinned = None

    async def unload(self) -> bool:
        """Tear down the loaded model to free VRAM. Returns True if a model was unloaded, False if none
        was loaded. Refused with Busy while a job has the GPU pinned (pause/cancel the run first)."""
        async with self._lock:
            if self.pinned is not None:
                raise Busy(self.pinned, "(unload)")
            if not self._alive():
                self.current, self.proc = None, None
                return False
            await self._wait_drained()
            await asyncio.to_thread(self._stop, self.proc)
            self.current, self.proc = None, None
            return True

    @asynccontextmanager
    async def lease(self, name: str):
        """Ensure `name` is loaded, then hold a lease on it for the duration of the block. Yields the
        model's `ServeModel` (use `.port` to reach the backend). The swap lock is held only for the
        load-check + registration, then released — so concurrent same-model requests don't serialize."""
        async with self._lock:
            m = await self._ensure_locked(name)
            self._inflight += 1
            self._drained.clear()
            self._last_activity = self._clock()
        try:
            yield m
        finally:
            self._inflight -= 1
            self._last_activity = self._clock()
            if self._inflight == 0:
                self._drained.set()

    # --- idle unload ----------------------------------------------------------------------------

    async def _idle_check(self) -> None:
        if self.current is None or self._inflight > 0:
            return
        if self._clock() - self._last_activity <= self._idle_timeout:
            return
        async with self._lock:
            # re-check under the lock: a request may have arrived while we waited for it
            if self.current and self._inflight == 0 and \
                    self._clock() - self._last_activity > self._idle_timeout:
                await asyncio.to_thread(self._stop, self.proc)
                self.last_swap = {"from": self.current, "to": None}
                self.current, self.proc = None, None

    async def _idle_loop(self) -> None:
        interval = max(5.0, min(self._idle_timeout, 30.0))
        while True:
            await asyncio.sleep(interval)
            await self._idle_check()

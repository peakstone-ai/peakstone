"""The gateway FastAPI app: an OpenAI-compatible front that swaps the backing llama-server per request.

Endpoints:
- GET  /v1/models                  list every model in serve/models.toml (OpenAI shape)
- POST /v1/chat/completions        ensure the named model is loaded, then reverse-proxy (streams SSE)
- POST /v1/completions             (same, legacy completion endpoint)
- POST /v1/embeddings              (same, if the loaded model serves embeddings)
- GET  /health                     daemon liveness + which model is currently loaded
- GET  /status                     full swap state (current model, idle timer, last swap, roster)

The model named in the request body selects the backend; llama-server itself uses whatever weights
are loaded, so the body is forwarded byte-for-byte. Responses stream straight through, so SSE token
deltas reach the client live.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..engine import paths
from . import auth as gw_auth
from .jobs import JobManager, JobStore
from .launch import load_gateway_config  # re-exported: config lives in launch (single source of truth)
from .swap import Busy, ModelManager, ServeFailed, UnknownModel

# Per-request headers we forward upstream / drop. Hop-by-hop and length headers must not be copied
# (we re-stream the body, so the original framing no longer applies).
_DROP_REQUEST_HEADERS = {"host", "content-length", "connection", "accept-encoding"}
_DROP_RESPONSE_HEADERS = {"content-length", "transfer-encoding", "connection", "content-encoding"}


def _default_submit(bundle: dict) -> tuple[int, str]:
    """Auto-submit a finished run's bundle to the leaderboard API (PEAKSTONE_API_URL). Best-effort:
    the dashboard client is stdlib-only and tolerates the API being down (raises, caught upstream)."""
    from ..dashboard.client import API_DEFAULT, submit_bundle
    return submit_bundle(API_DEFAULT, bundle)


def build_app(*, manager: ModelManager | None = None, idle_timeout: float = 0.0,
              client: httpx.AsyncClient | None = None, token: str | None = None,
              self_url: str | None = None, store: JobStore | None = None, submit=_default_submit,
              start_worker: bool = True) -> FastAPI:
    """Construct the gateway app. Pass `manager`/`client`/`store`/`token` to inject them (tests stub
    them so no real llama-server or runner is launched); otherwise defaults are created on startup. An
    injected client is left for the caller to close. `token` empty string disables auth."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.token = gw_auth.load_or_create_token() if token is None else token
        app.state.manager = manager or ModelManager(idle_timeout=idle_timeout)
        owns_client = client is None
        app.state.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=None, pool=None))
        url = self_url or f"http://127.0.0.1:{load_gateway_config()['port']}"
        app.state.jobs = JobManager(store or JobStore(), app.state.manager, gateway_url=url,
                                    submit=submit)
        app.state.manager.start()
        if start_worker:
            app.state.jobs.start()
        try:
            yield
        finally:
            await app.state.jobs.aclose()
            await app.state.manager.aclose()
            if owns_client:
                await app.state.client.aclose()

    app = FastAPI(title="Peakstone Gateway", version="0.1.0", lifespan=lifespan)

    async def require_auth(request: Request) -> None:
        """Loopback-exempt bearer auth. Empty token disables it."""
        token_ = request.app.state.token
        if not token_ or gw_auth.client_is_loopback(request):
            return
        presented = gw_auth.bearer_token(request)
        if presented and secrets.compare_digest(presented, token_):
            return
        raise HTTPException(status_code=401,
                            detail="missing or invalid bearer token (Authorization: Bearer <token>)")

    auth_dep = [Depends(require_auth)]

    @app.get("/health")                          # open: liveness probes need no token
    def health():
        mgr: ModelManager = app.state.manager
        return {"status": "ok", "model": mgr.current, "alive": mgr._alive()}

    @app.get("/status", dependencies=auth_dep)
    def status():
        return {**app.state.manager.status(), "jobs": app.state.jobs.list()[:20]}

    @app.get("/v1/models", dependencies=auth_dep)
    def list_models():
        mgr: ModelManager = app.state.manager
        data = [{"id": name, "object": "model", "owned_by": "peakstone",
                 "loaded": name == mgr.current} for name in sorted(mgr.registry())]
        return {"object": "list", "data": data}

    async def _proxy(path: str, request: Request):
        mgr: ModelManager = app.state.manager
        client: httpx.AsyncClient = app.state.client
        body = await request.body()
        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            raise HTTPException(status_code=400, detail="request body is not valid JSON")
        model = payload.get("model")
        if not model:
            raise HTTPException(status_code=400, detail="request is missing the 'model' field")

        # Enter the lease BEFORE streaming so swap/load errors surface as clean HTTP statuses rather
        # than a half-streamed 200. The lease (and the upstream stream) are held open by the response
        # generator until the body is fully relayed.
        lease = mgr.lease(model)
        try:
            m = await lease.__aenter__()
        except UnknownModel:
            raise HTTPException(status_code=404,
                                detail=f"unknown model {model!r} — see GET /v1/models")
        except Busy as e:
            raise HTTPException(status_code=503, detail=str(e))
        except ServeFailed as e:
            raise HTTPException(status_code=503, detail=str(e))

        url = f"http://localhost:{m.port}{path}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST_HEADERS}
        req = client.build_request("POST", url, content=body, headers=headers)
        try:
            upstream = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            await lease.__aexit__(type(e), e, e.__traceback__)
            raise HTTPException(status_code=502, detail=f"backend {model} unreachable: {e}")

        async def relay():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await lease.__aexit__(None, None, None)

        resp_headers = {k: v for k, v in upstream.headers.items()
                        if k.lower() not in _DROP_RESPONSE_HEADERS}
        return StreamingResponse(relay(), status_code=upstream.status_code, headers=resp_headers,
                                 media_type=upstream.headers.get("content-type"))

    @app.post("/v1/chat/completions", dependencies=auth_dep)
    async def chat_completions(request: Request):
        return await _proxy("/v1/chat/completions", request)

    @app.post("/v1/completions", dependencies=auth_dep)
    async def completions(request: Request):
        return await _proxy("/v1/completions", request)

    @app.post("/v1/embeddings", dependencies=auth_dep)
    async def embeddings(request: Request):
        return await _proxy("/v1/embeddings", request)

    # --- job control -----------------------------------------------------------------------------

    @app.post("/jobs", status_code=201, dependencies=auth_dep)
    async def enqueue_job(spec: dict):
        mgr: ModelManager = app.state.manager
        model = spec.get("model")
        if not model:
            raise HTTPException(status_code=400, detail="job spec is missing the 'model' field")
        if model not in mgr.registry():
            raise HTTPException(status_code=404, detail=f"unknown model {model!r} — see GET /v1/models")
        jid = app.state.jobs.enqueue(spec)
        return {"id": jid, "status": "queued"}

    @app.get("/jobs", dependencies=auth_dep)
    async def list_jobs():
        return {"jobs": app.state.jobs.list()}

    @app.get("/jobs/{jid}", dependencies=auth_dep)
    async def get_job(jid: str):
        job = app.state.jobs.get(jid)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job {jid!r}")
        return job

    @app.delete("/jobs/{jid}", dependencies=auth_dep)
    async def cancel_job(jid: str):
        if not app.state.jobs.cancel(jid):
            raise HTTPException(status_code=409, detail=f"job {jid!r} is unknown or already finished")
        return {"id": jid, "status": "cancelling"}

    @app.get("/jobs/{jid}/log", dependencies=auth_dep)
    async def job_log(jid: str, request: Request):
        """Tail a job's log as Server-Sent Events: replay what's written, then follow until the job
        finishes (and the client can disconnect anytime without affecting the run)."""
        job = app.state.jobs.get(jid)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job {jid!r}")

        async def events():
            path = paths.repo_root() / "results" / f"job-{jid}" / "run.log"
            pos = 0
            while True:
                if await request.is_disconnected():
                    return
                if path.exists():
                    with open(path) as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for line in chunk.splitlines():
                        yield f"data: {line}\n\n"
                cur = app.state.jobs.get(jid)
                if cur is None or cur["status"] not in ("queued", "running"):
                    yield "event: done\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def run(host: str | None = None, port: int | None = None, idle_timeout: float | None = None) -> None:
    """Launch the gateway with uvicorn. Unset args fall back to the [gateway] config / defaults."""
    import uvicorn

    cfg = load_gateway_config()
    host = host if host is not None else cfg["host"]
    port = port if port is not None else cfg["port"]
    idle_timeout = idle_timeout if idle_timeout is not None else cfg["idle_timeout_s"]
    token = gw_auth.load_or_create_token()
    app = build_app(idle_timeout=idle_timeout, token=token,
                    self_url=f"http://127.0.0.1:{port}")
    print(f">>> peakstone gateway on http://{host}:{port}/v1  (OpenAI-compatible; model-swapping)")
    print(f">>> idle-unload: {f'{idle_timeout:g}s' if idle_timeout > 0 else 'off'}")
    if host not in ("127.0.0.1", "localhost"):
        # exposed beyond loopback → LAN clients (editors, etc.) must present this token
        print(f">>> auth token (paste into your editor's API-key field): {token}")
        print(f">>>   stored at {gw_auth.TOKEN_PATH}  ·  loopback is exempt")
    uvicorn.run(app, host=host, port=port)

"""Gateway tests — no GPU, no real llama-server, no real runner subprocess.

The ModelManager's blocking primitives (serve/wait/stop) are stubbed so the real lock/swap/drain/pin
logic runs against fake processes; the upstream HTTP backend is an httpx MockTransport; and the job
worker's `stream_runner` is monkeypatched so jobs "run" without spawning the engine.

`PEAKSTONE_HOME`/`PEAKSTONE_REPO` are redirected to a tmp dir (autouse) so the auth-token file and
jobs.db never touch the real home/repo.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from peakstone.engine.serving import ServeModel
from peakstone.gateway import auth as gw_auth
from peakstone.gateway.app import build_app
from peakstone.gateway.jobs import JobManager, JobStore, summarize_bundle
from peakstone.gateway.swap import Busy, ModelManager, ServeFailed, UnknownModel


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("PEAKSTONE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PEAKSTONE_REPO", str(tmp_path / "repo"))


class FakeProc:
    """A live serve/runner subprocess stand-in: poll() is None until killed."""
    def __init__(self):
        self.killed = False

    def poll(self):
        return 0 if self.killed else None


def make_manager(*, serve_calls=None, stop_calls=None, healthy=True, **kw):
    """A ModelManager over a 2-model registry with stubbed serve/wait/stop."""
    serve_calls = serve_calls if serve_calls is not None else []
    stop_calls = stop_calls if stop_calls is not None else []
    registry = {
        "model-a": ServeModel("model-a", port=9001, ctx=4096, file=None, flags=""),
        "model-b": ServeModel("model-b", port=9002, ctx=4096, file=None, flags=""),
    }

    def fake_serve(name, **_):
        serve_calls.append(name)
        return FakeProc()

    def fake_wait(port, **_):
        return healthy

    def fake_stop(proc):
        if proc is not None:
            proc.killed = True
            stop_calls.append(proc)

    return ModelManager(registry=registry, _serve=fake_serve, _wait=fake_wait, _stop=fake_stop,
                        _log_tail=lambda n: "fake-oom", **kw)


def mock_client(ports_hit):
    """An httpx client whose backend records the port it was called on and streams a tiny SSE body.
    The body is an async generator so the response is a real stream (what aiter_raw expects)."""
    def handler(request: httpx.Request) -> httpx.Response:
        ports_hit.append(request.url.port)

        async def sse():
            yield b"data: hi\n\n"
            yield b"data: [DONE]\n\n"

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse())
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def client_for(manager, client, *, token="", start_worker=False, **kw):
    """A TestClient over the app with auth disabled and the job worker off by default (so queued jobs
    stay queued for deterministic REST assertions). Tests that need them override."""
    return TestClient(build_app(manager=manager, client=client, token=token,
                                start_worker=start_worker, submit=None, **kw))


# --- HTTP surface (auth disabled) ------------------------------------------------------------

def test_list_models_reflects_registry():
    mgr = make_manager()
    with client_for(mgr, mock_client([])) as c:
        body = c.get("/v1/models").json()
    ids = [m["id"] for m in body["data"]]
    assert body["object"] == "list" and ids == ["model-a", "model-b"]
    assert all(m["loaded"] is False for m in body["data"])   # nothing loaded yet


def test_proxy_loads_swaps_and_streams():
    serve_calls, stop_calls, ports = [], [], []
    mgr = make_manager(serve_calls=serve_calls, stop_calls=stop_calls)
    with client_for(mgr, mock_client(ports)) as c:
        r1 = c.post("/v1/chat/completions", json={"model": "model-a", "messages": []})
        assert r1.status_code == 200 and "data: hi" in r1.text
        r2 = c.post("/v1/chat/completions", json={"model": "model-b", "messages": []})
        assert r2.status_code == 200
        c.post("/v1/chat/completions", json={"model": "model-b", "messages": []})  # same → no swap
        assert len(stop_calls) == 1                      # model-a stopped, exactly once, on the swap

    assert serve_calls == ["model-a", "model-b"]       # loaded a, swapped to b, b stayed
    assert ports == [9001, 9002, 9002]                   # each request routed to its model's port
    assert mgr.last_swap == {"from": "model-a", "to": "model-b"}


def test_unknown_model_is_404():
    with client_for(make_manager(), mock_client([])) as c:
        r = c.post("/v1/chat/completions", json={"model": "nope", "messages": []})
    assert r.status_code == 404


def test_missing_model_is_400():
    with client_for(make_manager(), mock_client([])) as c:
        r = c.post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 400


def test_serve_failure_is_503():
    mgr = make_manager(healthy=False)            # llama-server never becomes healthy
    with client_for(mgr, mock_client([])) as c:
        r = c.post("/v1/chat/completions", json={"model": "model-a", "messages": []})
    assert r.status_code == 503 and "fake-oom" in r.json()["detail"]


def test_health_and_status():
    mgr = make_manager()
    with client_for(mgr, mock_client([])) as c:
        assert c.get("/health").json() == {"status": "ok", "model": None, "alive": False}
        c.post("/v1/chat/completions", json={"model": "model-a", "messages": []})
        st = c.get("/status").json()
    assert st["current"] == "model-a" and st["inflight"] == 0 and st["models"] == ["model-a", "model-b"]


# --- auth --------------------------------------------------------------------------------------

class FakeReq:
    def __init__(self, host, headers=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


def test_auth_dependency_loopback_and_token():
    dep = gw_auth.make_auth_dependency("sekret")
    asyncio.run(dep(FakeReq("127.0.0.1")))                                  # loopback → exempt
    asyncio.run(dep(FakeReq("::1")))                                        # ipv6 loopback → exempt
    asyncio.run(dep(FakeReq("192.168.1.9", {"authorization": "Bearer sekret"})))  # LAN + token → ok
    with pytest.raises(HTTPException) as ei:
        asyncio.run(dep(FakeReq("192.168.1.9")))                           # LAN, no token → 401
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException):
        asyncio.run(dep(FakeReq("192.168.1.9", {"authorization": "Bearer wrong"})))
    asyncio.run(gw_auth.make_auth_dependency("")(FakeReq("192.168.1.9")))   # empty token → auth off


def test_http_auth_lan_path():
    """TestClient presents a non-loopback host, so a set token is enforced over HTTP."""
    mgr = make_manager()
    app = build_app(manager=mgr, client=mock_client([]), token="sekret", start_worker=False,
                    submit=None)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200                          # open endpoint
        assert c.get("/v1/models").status_code == 401                       # protected, no token
        assert c.get("/v1/models", headers={"Authorization": "Bearer sekret"}).status_code == 200
        assert c.get("/v1/models", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_token_file_is_created_0600(tmp_path, monkeypatch):
    import os
    home = tmp_path / "h"
    monkeypatch.setenv("PEAKSTONE_HOME", str(home))
    monkeypatch.delenv("PEAKSTONE_GATEWAY_TOKEN", raising=False)
    tok = gw_auth.load_or_create_token()
    assert tok.startswith("pk-") and gw_auth.TOKEN_PATH.exists()
    assert oct(gw_auth.TOKEN_PATH.stat().st_mode)[-3:] == "600"
    assert gw_auth.load_or_create_token() == tok                            # stable across calls


def test_env_token_overrides_file(monkeypatch):
    monkeypatch.setenv("PEAKSTONE_GATEWAY_TOKEN", "from-env")
    assert gw_auth.load_or_create_token() == "from-env"


# --- pin (GPU sharing during a job) -----------------------------------------------------------

def test_pin_rejects_other_model_with_503():
    async def scenario():
        mgr = make_manager()
        await mgr.pin("model-a")
        # same model is fine (shares the loaded server)
        async with mgr.lease("model-a"):
            pass
        # a different model is refused while pinned
        with pytest.raises(Busy):
            await mgr.ensure_loaded("model-b")
        mgr.unpin()
        await mgr.ensure_loaded("model-b")            # released → swaps freely
        assert mgr.current == "model-b"
        await mgr.aclose()

    asyncio.run(scenario())


def test_pin_surfaces_in_http_503():
    mgr = make_manager()
    with client_for(mgr, mock_client([])) as c:
        asyncio.run(mgr.pin("model-a"))               # a "job" owns the GPU
        ok = c.post("/v1/chat/completions", json={"model": "model-a", "messages": []})
        busy = c.post("/v1/chat/completions", json={"model": "model-b", "messages": []})
    assert ok.status_code == 200 and busy.status_code == 503
    assert "busy" in busy.json()["detail"]


# --- jobs: REST surface (worker off) ----------------------------------------------------------

def test_jobs_rest_lifecycle(tmp_path):
    mgr = make_manager()
    with client_for(mgr, mock_client([]), store=JobStore(tmp_path / "jobs.db"),
                    present=lambda *_: True) as c:
        r = c.post("/jobs", json={"model": "model-a", "ids": ["x"]})
        assert r.status_code == 201
        jid = r.json()["id"]
        assert c.get("/jobs").json()["jobs"][0]["id"] == jid
        assert c.get(f"/jobs/{jid}").json()["status"] == "queued"
        assert c.delete(f"/jobs/{jid}").status_code == 200            # cancel a queued job
        assert c.get(f"/jobs/{jid}").json()["status"] == "cancelled"
        assert c.get("/jobs/ghost").status_code == 404
        assert c.post("/jobs", json={"ids": []}).status_code == 400   # missing model
        assert c.post("/jobs", json={"model": "ghost"}).status_code == 404


# --- jobs: execution (worker on, stubbed runner) ----------------------------------------------

def _fake_stream_ok(cmd, *, out, timeout, env_extra=None, log=lambda s: None, on_proc=None, popen=None):
    on_proc and on_proc(FakeProc())
    log("solving c1")
    log("c1 ok")
    return {"bundle_hash": "abc123",
            "results": [{"verification": "deterministic-tests",
                         "score": {"final": 1.0, "passed": 3, "total": 3}, "tok_per_s": 50.0}]}


def test_job_runs_to_completion(monkeypatch, tmp_path):
    import peakstone.engine.serving as serving
    monkeypatch.setattr(serving, "stream_runner", _fake_stream_ok)

    async def scenario():
        mgr = make_manager()
        store = JobStore(tmp_path / "jobs.db")                 # isolated queue (don't touch the real db)
        jm = JobManager(store, mgr, gateway_url="http://127.0.0.1:11434", submit=None,
                        present=lambda *_: True)
        jm.start()
        jid = jm.enqueue({"model": "model-a", "ids": ["x"]})
        for _ in range(200):                                   # let the worker run the job
            if store.get(jid)["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(0.02)
        job = store.get(jid)
        assert job["status"] == "done"
        assert job["summary"]["passed"] == 3 and job["summary"]["code_score"] == 1.0
        assert mgr.pinned is None                              # unpinned after the job
        assert mgr.current == "model-a"                        # pin loaded the model
        await jm.aclose()

    asyncio.run(scenario())


def test_job_cancelled_during_load_never_runs(monkeypatch, tmp_path):
    import peakstone.engine.serving as serving
    ran = []
    monkeypatch.setattr(serving, "stream_runner",
                        lambda *a, **k: ran.append(1) or {"results": []})

    async def scenario():
        mgr = make_manager()
        store = JobStore(tmp_path / "jobs.db")
        jm = JobManager(store, mgr, gateway_url="http://127.0.0.1:11434", submit=None,
                        present=lambda *_: True)
        jid = jm.enqueue({"model": "model-a"})
        jm._cancel_requested.add(jid)                 # cancel lands as the job starts loading
        jm.start()
        for _ in range(200):
            if store.get(jid)["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(0.02)
        assert store.get(jid)["status"] == "cancelled"
        assert ran == [] and mgr.pinned is None       # runner never launched; GPU released
        await jm.aclose()

    asyncio.run(scenario())


def test_run_auto_downloads_then_runs(monkeypatch, tmp_path):
    """Enqueuing a run for a model that isn't on disk auto-queues its download (separate queue); once
    the weights land, the run executes."""
    import peakstone.engine.serving as serving
    monkeypatch.setattr(serving, "stream_runner", _fake_stream_ok)
    present = {"model-a": False}

    def download(model, log, cancel):
        log(f"fetching {model}")
        present[model] = True                                   # weights now on disk
        return True

    async def scenario():
        mgr = make_manager()
        store = JobStore(tmp_path / "jobs.db")
        jm = JobManager(store, mgr, gateway_url="http://x", submit=None,
                        present=lambda m: present.get(m, False), download=download)
        jm.start()
        jid = jm.enqueue({"model": "model-a", "ids": ["x"]})    # missing → auto-download, then run
        for _ in range(300):
            if store.get(jid)["status"] in ("done", "failed", "cancelled"):
                break
            await asyncio.sleep(0.02)
        assert store.get(jid)["status"] == "done"
        dls = [j for j in store.list() if j["kind"] == "download"]
        assert dls and dls[0]["status"] == "done" and dls[0]["spec"]["model"] == "model-a"
        await jm.aclose()

    asyncio.run(scenario())


def test_gpu_not_idle_while_downloading(monkeypatch, tmp_path):
    """A ready run must never wait behind a model that's still downloading: the run scheduler picks the
    oldest run whose weights are present, so the GPU stays busy."""
    import peakstone.engine.serving as serving
    import threading
    monkeypatch.setattr(serving, "stream_runner", _fake_stream_ok)
    present = {"model-a": False, "model-b": True}
    release = threading.Event()

    def download(model, log, cancel):
        release.wait(2.0)                                      # hold model-a's download open
        present[model] = True
        return True

    async def scenario():
        mgr = make_manager()
        store = JobStore(tmp_path / "jobs.db")
        jm = JobManager(store, mgr, gateway_url="http://x", submit=None,
                        present=lambda m: present.get(m, False), download=download)
        jm.start()
        a = jm.enqueue({"model": "model-a"})                   # missing → downloads (held open)
        b = jm.enqueue({"model": "model-b"})                   # ready → should run NOW, not wait for a
        for _ in range(200):
            if store.get(b)["status"] == "done":
                break
            await asyncio.sleep(0.02)
        assert store.get(b)["status"] == "done"                # b ran while a was still downloading
        assert store.get(a)["status"] in ("queued", "running")  # a hasn't finished (download held)
        release.set()
        for _ in range(200):
            if store.get(a)["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.02)
        assert store.get(a)["status"] == "done"
        await jm.aclose()

    asyncio.run(scenario())


def test_pause_skips_then_resume_runs(monkeypatch, tmp_path):
    """A paused queued job is skipped by the scheduler (the next ready one runs); resume re-queues it."""
    import peakstone.engine.serving as serving
    monkeypatch.setattr(serving, "stream_runner", _fake_stream_ok)

    async def scenario():
        mgr = make_manager()
        store = JobStore(tmp_path / "jobs.db")
        jm = JobManager(store, mgr, gateway_url="http://x", submit=None, present=lambda *_: True)
        a = jm.enqueue({"model": "model-a"})
        b = jm.enqueue({"model": "model-b"})
        assert jm.pause(a) and store.get(a)["status"] == "paused"   # pause the (queued) first job
        jm.start()
        for _ in range(200):                                        # b runs; a is skipped
            if store.get(b)["status"] == "done":
                break
            await asyncio.sleep(0.02)
        assert store.get(b)["status"] == "done" and store.get(a)["status"] == "paused"
        assert jm.resume(a)                                         # resume → re-queued → runs
        for _ in range(200):
            if store.get(a)["status"] == "done":
                break
            await asyncio.sleep(0.02)
        assert store.get(a)["status"] == "done"
        await jm.aclose()

    asyncio.run(scenario())


def test_pause_resume_endpoints(tmp_path):
    mgr = make_manager()
    with client_for(mgr, mock_client([]), store=JobStore(tmp_path / "jobs.db"),
                    present=lambda *_: True) as c:
        jid = c.post("/jobs", json={"model": "model-a"}).json()["id"]
        assert c.post(f"/jobs/{jid}/pause").status_code == 200
        assert c.get(f"/jobs/{jid}").json()["status"] == "paused"
        assert c.post(f"/jobs/{jid}/resume").status_code == 200
        assert c.get(f"/jobs/{jid}").json()["status"] == "queued"
        assert c.post("/jobs/ghost/pause").status_code == 409          # not pausable
        assert c.post(f"/jobs/{jid}/resume").status_code == 409        # not paused (already queued)


def test_unload_frees_vram_and_refuses_while_pinned(tmp_path):
    async def pinned():
        mgr = make_manager()
        await mgr.pin("model-a")                                       # a job owns the GPU
        with pytest.raises(Busy):
            await mgr.unload()
        mgr.unpin()
        await mgr.aclose()
    asyncio.run(pinned())

    stop_calls = []
    mgr = make_manager(stop_calls=stop_calls)
    with client_for(mgr, mock_client([])) as c:
        assert c.post("/unload").json() == {"unloaded": False}        # nothing loaded yet
        c.post("/v1/chat/completions", json={"model": "model-a", "messages": []})   # load it
        assert c.post("/unload").json() == {"unloaded": True}
        assert len(stop_calls) >= 1                                    # llama-server torn down


def test_summarize_bundle():
    s = summarize_bundle({"bundle_hash": "h", "results": [
        {"verification": "deterministic-tests", "score": {"final": 0.5, "passed": 1, "total": 2}, "tok_per_s": 40},
        {"verification": "deterministic-tests", "score": {"final": 1.0, "passed": 2, "total": 2}, "tok_per_s": 60},
    ]})
    assert s["passed"] == 3 and s["total"] == 4 and s["code_score"] == 0.75 and s["your_tps"] == 50.0


def test_store_reaps_interrupted():
    store = JobStore()
    jid = store.enqueue({"model": "model-a"}, now=1.0)
    store.update(jid, status="running", started=2.0)
    assert store.reap_interrupted() == 1
    assert store.get(jid)["status"] == "interrupted"


# --- swap/drain invariant (direct, async) ----------------------------------------------------

def test_swap_waits_for_inflight_to_drain():
    async def scenario():
        stop_calls = []
        mgr = make_manager(stop_calls=stop_calls)
        swapped = asyncio.Event()

        async def do_swap():
            async with mgr.lease("model-b"):
                swapped.set()

        hold = mgr.lease("model-a")
        await hold.__aenter__()                       # model-a loaded, inflight = 1
        assert mgr.current == "model-a"
        task = asyncio.create_task(do_swap())
        await asyncio.sleep(0.05)                      # give the swap a chance to (not) proceed
        assert not swapped.is_set()                    # blocked: draining model-a's in-flight request
        assert mgr.current == "model-a" and not stop_calls
        await hold.__aexit__(None, None, None)         # inflight → 0, drain unblocks
        await asyncio.wait_for(task, timeout=1.0)
        assert swapped.is_set() and mgr.current == "model-b"
        assert len(stop_calls) == 1                    # model-a torn down only after it drained
        await mgr.aclose()

    asyncio.run(scenario())


def test_ensure_loaded_no_swap_when_already_current():
    async def scenario():
        serve_calls = []
        mgr = make_manager(serve_calls=serve_calls)
        await mgr.ensure_loaded("model-a")
        await mgr.ensure_loaded("model-a")            # already current + healthy → no re-serve
        assert serve_calls == ["model-a"]
        await mgr.aclose()

    asyncio.run(scenario())


def test_unknown_model_raises():
    async def scenario():
        mgr = make_manager()
        with pytest.raises(UnknownModel):
            await mgr.ensure_loaded("ghost")
        await mgr.aclose()

    asyncio.run(scenario())


def test_serve_failed_raises_with_tail():
    async def scenario():
        mgr = make_manager(healthy=False)
        with pytest.raises(ServeFailed) as ei:
            await mgr.ensure_loaded("model-a")
        assert "fake-oom" in ei.value.log_tail
        await mgr.aclose()

    asyncio.run(scenario())


# --- end-to-end wiring (real gateway + fake llama-server, no GPU) ------------------------------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _make_backend(text):
    """A fake llama-server: /health → 200, /v1/chat/completions → an SSE stream emitting `text`."""
    import http.server
    import json as _json

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()
            if self.path == "/health":
                self.wfile.write(b"ok")

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0) or 0))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            delta = {"choices": [{"index": 0, "delta": {"content": text}}]}
            final = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
            self.wfile.write(f"data: {_json.dumps(delta)}\n\n".encode())
            self.wfile.write(f"data: {_json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return H


def test_end_to_end_real_gateway_proxies_and_swaps():
    """The runner's actual generation path, minus the GPU: provider.LLMClient → a REAL uvicorn gateway
    → reverse-proxy → a fake llama-server, streamed back. Two models on two backends prove the swap
    routes to the right one. Stubs only the serve/health primitives (the fake backends are already up)."""
    import http.server
    import threading
    import time

    import uvicorn

    from peakstone.engine.provider import LLMClient
    from peakstone.engine.serving import ServeModel

    # two fake backends on ephemeral ports
    srv_a = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_backend("alpha"))
    srv_b = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_backend("bravo"))
    port_a, port_b = srv_a.server_address[1], srv_b.server_address[1]
    threading.Thread(target=srv_a.serve_forever, daemon=True).start()
    threading.Thread(target=srv_b.serve_forever, daemon=True).start()

    registry = {"model-a": ServeModel("model-a", port=port_a, ctx=4096, file=None, flags=""),
                "model-b": ServeModel("model-b", port=port_b, ctx=4096, file=None, flags="")}
    # serve() is a no-op (the backend is already listening); wait() reports healthy.
    mgr = ModelManager(registry=registry, _serve=lambda name, **_: FakeProc(),
                       _wait=lambda port, **_: True, _stop=lambda p: None)

    gw_port = _free_port()
    app = build_app(manager=mgr, token="", start_worker=False, submit=None)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=gw_port, log_level="error"))
    gw_thread = threading.Thread(target=server.run, daemon=True)
    gw_thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "gateway did not start"

        cl = LLMClient(f"http://127.0.0.1:{gw_port}")
        cl.stream = True                                  # the runner streams (loop detection)
        assert cl.health()                                # provider → gateway /v1/models

        r1 = cl.chat("model-a", [{"role": "user", "content": "hi"}], max_tokens=16)
        assert r1.error is None and r1.text == "alpha"    # proxied to backend A, streamed back
        r2 = cl.chat("model-b", [{"role": "user", "content": "hi"}], max_tokens=16)
        assert r2.error is None and r2.text == "bravo"    # swapped → routed to backend B
        assert mgr.last_swap == {"from": "model-a", "to": "model-b"}
    finally:
        server.should_exit = True
        gw_thread.join(timeout=5)
        srv_a.shutdown()
        srv_b.shutdown()

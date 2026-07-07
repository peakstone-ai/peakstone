"""R17-R19 — daemon lifecycle. Shutdown must kill the in-flight runner; a wedged stream must not
deadlock the swap; interrupted jobs re-queue; a foreign server on the port is never adopted;
/admin/shutdown gives the TUI/CLI a graceful restart lever."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import time

import peakstone.engine.serving as serving
from peakstone.gateway.jobs import JobManager, JobStore
from peakstone.gateway.tests.test_gateway import client_for, make_manager, mock_client


def test_aclose_kills_inflight_runner_before_worker_cancel(monkeypatch, tmp_path):
    """R17: the cancelled _run_job's `finally` nulls _current — the old aclose checked it only
    AFTER cancelling, so the runner always survived shutdown as an orphan."""
    stopped = []
    monkeypatch.setattr(serving, "stop", lambda p: stopped.append(p))

    async def scenario():
        jm = JobManager(JobStore(tmp_path / "j.db"), make_manager(), gateway_url="http://x",
                        submit=None)
        proc = object()
        jm._current = {"id": "j", "proc": proc}

        async def fake_worker():   # what a cancelled _run_job does on the way out
            try:
                await asyncio.sleep(3600)
            finally:
                jm._current = None

        jm._tasks = [asyncio.create_task(fake_worker())]
        await asyncio.sleep(0)
        await jm.aclose()
        assert stopped == [proc]

    asyncio.run(scenario())


def test_drain_deadline_breaks_the_deadlock(monkeypatch):
    """R18: one wedged in-flight stream froze every subsequent swap forever."""
    mgr = make_manager()
    monkeypatch.setattr(type(mgr), "DRAIN_DEADLINE_S", 0.2)
    mgr._inflight = 1                       # a stream that never finishes

    async def scenario():
        await asyncio.wait_for(mgr._wait_drained(), timeout=5)   # returns; used to hang

    asyncio.run(scenario())


def test_interrupted_jobs_requeue_on_startup(tmp_path):
    """R19: a daemon crash/restart re-queues what was running (nothing could resume 'interrupted'),
    including downloads — so dependent runs stop failing as 'not downloaded'."""
    store = JobStore(tmp_path / "j.db")
    run = store.enqueue({"model": "m"}, kind="run", now=1.0)
    dl = store.enqueue({"model": "m"}, kind="download", now=1.0)
    store.update(run, status="running", started=2.0)
    store.update(dl, status="running", started=2.0)
    assert store.reap_interrupted() == 2
    assert store.get(run)["status"] == "queued" and store.get(dl)["status"] == "queued"


class _Resp:
    def __init__(self, body: bytes):
        self._body, self.status = body, 200

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_wait_healthy_refuses_foreign_server():
    """R19: a 200 on the port is not OUR server — an orphan llama-server serving a different
    model must not be silently adopted under the requested name."""
    def foreign(url, timeout=3):
        return _Resp(json.dumps({"model_path": "/models/OTHER.gguf"}).encode()
                     if url.endswith("/props") else b"{}")

    def ours(url, timeout=3):
        return _Resp(json.dumps({"model_path": "/x/mine.gguf"}).encode()
                     if url.endswith("/props") else b"{}")

    def no_props(url, timeout=3):
        if url.endswith("/props"):
            raise OSError("no /props")
        return _Resp(b"{}")

    assert serving.wait_healthy(7777, timeout=1, opener=foreign, expected_file="m/mine.gguf") is False
    assert serving.wait_healthy(7777, timeout=5, opener=ours, expected_file="m/mine.gguf") is True
    assert serving.wait_healthy(7777, timeout=5, opener=no_props, expected_file="m/mine.gguf") is True


def test_admin_shutdown_responds_then_sigterms(monkeypatch):
    kills = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
    with client_for(make_manager(), mock_client([])) as c:
        r = c.post("/admin/shutdown")
        assert r.status_code == 200 and r.json()["status"] == "shutting-down"
        time.sleep(0.6)                     # let call_later(0.3) fire on the app loop
    assert kills and kills[0] == (os.getpid(), signal.SIGTERM)

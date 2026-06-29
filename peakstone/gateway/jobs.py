"""Benchmark job queue — owned by the daemon, persisted, so runs survive client disconnects.

`JobStore` is a tiny stdlib-sqlite table at results/jobs.db. `JobManager` runs a single async worker
that drains queued jobs one at a time (one GPU): for each it pins the GPU to the job's model, spawns
the engine runner pointed back at this same gateway (`--gateway`, so the ModelManager does the
serving), streams stdout to the job's log file, parses the bundle, and optionally auto-submits it to
the leaderboard. Cancel kills the runner's process group.

The TUI/CLI are thin clients over the HTTP endpoints in app.py; nothing here depends on Textual.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path

from ..engine import paths, serving
from .swap import ModelManager

STATUSES = ("queued", "running", "done", "failed", "cancelled", "interrupted")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["spec"] = json.loads(d["spec"]) if d.get("spec") else {}
    d["summary"] = json.loads(d["summary"]) if d.get("summary") else None
    return d


class JobStore:
    """Persistent job records. Each method opens its own short-lived connection so it's safe to call
    from the worker thread and the event loop alike."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else (paths.repo_root() / "results" / "jobs.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL,
                created REAL, started REAL, finished REAL, summary TEXT, log TEXT)""")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def enqueue(self, spec: dict, *, now: float) -> str:
        jid = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute("INSERT INTO jobs(id, spec, status, created) VALUES(?,?,?,?)",
                      (jid, json.dumps(spec), "queued", now))
        return jid

    def list(self, *, limit: int = 200) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get(self, jid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return _row_to_dict(row) if row else None

    def next_queued(self) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        return _row_to_dict(row) if row else None

    def update(self, jid: str, **fields) -> None:
        if "summary" in fields and not isinstance(fields["summary"], (str, type(None))):
            fields["summary"] = json.dumps(fields["summary"])
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), jid))

    def reap_interrupted(self) -> int:
        """On daemon startup, any job left 'running' was orphaned by a crash/restart — mark it so."""
        with self._conn() as c:
            cur = c.execute("UPDATE jobs SET status='interrupted' WHERE status='running'")
            return cur.rowcount


def summarize_bundle(bundle: dict) -> dict:
    """Headline numbers from a finished run's bundle — what the TUI/CLI shows per job."""
    results = bundle.get("results", []) or []
    tps = [r["tok_per_s"] for r in results if isinstance(r.get("tok_per_s"), (int, float))]
    codes = [r["score"]["final"] for r in results
             if r.get("verification") == "deterministic-tests" and isinstance(r.get("score"), dict)]
    passed = sum(r.get("score", {}).get("passed", 0) for r in results if isinstance(r.get("score"), dict))
    total = sum(r.get("score", {}).get("total", 0) for r in results if isinstance(r.get("score"), dict))
    return {
        "your_tps": round(sum(tps) / len(tps), 1) if tps else None,
        "code_score": round(sum(codes) / len(codes), 3) if codes else None,
        "passed": passed, "total": total, "n_challenges": len(results),
        "bundle_hash": bundle.get("bundle_hash") or (bundle.get("meta") or {}).get("bundle_hash"),
    }


class JobManager:
    """Owns the JobStore + the single background worker. Endpoints call enqueue/list/get/cancel."""

    def __init__(self, store: JobStore, manager: ModelManager, *, gateway_url: str,
                 submit=None, clock=time.time):
        self.store = store
        self.manager = manager
        self.gateway_url = gateway_url            # the daemon's own base URL (loopback) for --gateway
        self._submit = submit                     # callable(bundle) -> (status:int, detail) or None
        self._clock = clock
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._current: dict | None = None         # {"id", "proc"} of the running job
        self._cancel_requested: set[str] = set()
        self._stop = False

    # --- lifecycle ------------------------------------------------------------------------------

    def start(self) -> None:
        self.store.reap_interrupted()
        self._task = asyncio.create_task(self._run_loop())

    async def aclose(self) -> None:
        self._stop = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._current and self._current.get("proc"):
            serving.stop(self._current["proc"])

    # --- client-facing API ----------------------------------------------------------------------

    def enqueue(self, spec: dict) -> str:
        jid = self.store.enqueue(spec, now=self._clock())
        self._wake.set()
        return jid

    def list(self) -> list[dict]:
        return self.store.list()

    def get(self, jid: str) -> dict | None:
        return self.store.get(jid)

    def cancel(self, jid: str) -> bool:
        """Cancel a queued job (drop it) or a running job (kill its runner). False if unknown/finished.
        A running job is cancellable even during the model-load phase (before its runner subprocess
        exists): the flag is honored when the worker reaches its next checkpoint."""
        job = self.store.get(jid)
        if job is None:
            return False
        if job["status"] == "queued":
            self.store.update(jid, status="cancelled", finished=self._clock())
            return True
        if job["status"] == "running":
            self._cancel_requested.add(jid)
            if self._current and self._current["id"] == jid and self._current.get("proc"):
                serving.stop(self._current["proc"])   # kill the runner; worker finalizes as cancelled
            return True
        return False

    # --- worker ---------------------------------------------------------------------------------

    async def _run_loop(self) -> None:
        while not self._stop:
            job = self.store.next_queued()
            if job is None:
                self._wake.clear()
                await self._wake.wait()
                continue
            await self._run_job(job)

    async def _run_job(self, job: dict) -> None:
        jid, spec = job["id"], job["spec"]
        model = spec.get("model")
        out = paths.repo_root() / "results" / f"job-{jid}"
        out.mkdir(parents=True, exist_ok=True)
        logpath = out / "run.log"
        self.store.update(jid, status="running", started=self._clock(), log=str(logpath))

        def log(line: str) -> None:
            with open(logpath, "a") as f:
                f.write(line + "\n")

        try:
            await self.manager.pin(model)            # reserve the GPU + load the model now
        except Exception as e:  # noqa: BLE001  (UnknownModel/ServeFailed/etc.)
            self.manager.unpin()
            log(f"!! cannot load {model}: {e}")
            self.store.update(jid, status="failed", finished=self._clock(),
                              summary={"note": f"cannot load {model}: {e}"})
            return

        if jid in self._cancel_requested:            # cancelled while the model was loading
            self._cancel_requested.discard(jid)
            self.manager.unpin()
            self.store.update(jid, status="cancelled", finished=self._clock())
            return

        bundle = None
        try:
            cmd, timeout = serving.build_runner_cmd(model, spec.get("ids"), level=spec.get("level"),
                                                    out=out, max_tokens=spec.get("budget"),
                                                    gateway=self.gateway_url)
            env_extra = {}
            if spec.get("ctx"):
                env_extra["PEAKSTONE_CTX"] = str(spec["ctx"])
            rb = serving.reasoning_budget(spec.get("reasoning"))
            if rb is not None:
                env_extra["PEAKSTONE_REASONING_BUDGET"] = rb
            bundle = await asyncio.to_thread(
                serving.stream_runner, cmd, out=out, timeout=timeout, env_extra=env_extra, log=log,
                on_proc=lambda p: self._set_current(jid, p))
        finally:
            self.manager.unpin()
            self._current = None

        if jid in self._cancel_requested:
            self._cancel_requested.discard(jid)
            self.store.update(jid, status="cancelled", finished=self._clock())
            return
        if not bundle:
            self.store.update(jid, status="failed", finished=self._clock(),
                              summary={"note": "no bundle produced (run failed or was killed)"})
            return

        summary = summarize_bundle(bundle)
        if self._submit:
            try:
                status, _ = self._submit(bundle)
                summary["submitted"] = status in (201, 409)
            except Exception as e:  # noqa: BLE001
                summary["submit_error"] = str(e)
        self.store.update(jid, status="done", finished=self._clock(), summary=summary)

    def _set_current(self, jid: str, proc) -> None:
        self._current = {"id": jid, "proc": proc}

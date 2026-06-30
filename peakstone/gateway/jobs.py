"""Job queues — owned by the daemon, persisted, so work survives client disconnects.

`JobStore` is a tiny stdlib-sqlite table at results/jobs.db. Each job has a `kind`:
- "run"      — a benchmark. `JobManager` runs these one at a time (one GPU): pin the GPU to the
               model, spawn the engine runner pointed back at this gateway (`--gateway`, so the
               ModelManager does the serving), stream stdout to the job's log, parse the bundle,
               optionally auto-submit. Cancel kills the runner's process group.
- "download" — fetch a model's GGUF. These run on a SEPARATE worker, concurrent with runs (disk/
               network-bound, no GPU), so a download never blocks a run and vice-versa.

Scheduling rule: the run worker always picks the oldest queued run whose weights are already present
(ready to run) — it never leaves the GPU idle waiting on a download. A run whose model is still
downloading just waits its turn. Enqueuing a run for a missing model auto-enqueues its download, so
"run X" works even when X isn't on disk yet.

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

STATUSES = ("queued", "running", "paused", "done", "failed", "cancelled", "interrupted")


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
                id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'run',
                created REAL, started REAL, finished REAL, summary TEXT, log TEXT)""")
            cols = [r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()]
            if "kind" not in cols:           # migrate an older db (all pre-existing rows were runs)
                c.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'run'")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def enqueue(self, spec: dict, *, kind: str = "run", now: float) -> str:
        jid = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute("INSERT INTO jobs(id, spec, status, kind, created) VALUES(?,?,?,?,?)",
                      (jid, json.dumps(spec), "queued", kind, now))
        return jid

    def list(self, *, limit: int = 200) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get(self, jid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return _row_to_dict(row) if row else None

    def queued(self, kind: str) -> list[dict]:
        """All queued jobs of a kind, oldest first (the run scheduler picks among these by readiness)."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs WHERE status='queued' AND kind=? ORDER BY created",
                             (kind,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def active(self, kind: str) -> list[dict]:
        """Queued or running jobs of a kind (used to tell if a model already has a download in flight)."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs WHERE status IN ('queued','running') AND kind=?",
                             (kind,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def next_queued(self, kind: str = "download") -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE status='queued' AND kind=? ORDER BY created LIMIT 1",
                            (kind,)).fetchone()
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
        "run_status": bundle.get("run_status"),                   # "not_capable" for non-viable configs
        "abandoned_categories": bundle.get("abandoned_categories"),
    }


def _default_download(model: str, log, cancel) -> bool:
    """Fetch a model's GGUF via the dashboard registry (huggingface_hub). True if present afterwards.
    Imported lazily so the daemon doesn't pull the dashboard package unless a download actually runs."""
    from ..dashboard import models as dash_models
    entry = dash_models.load_registry().get(model)
    if entry is None:
        log(f"{model} is not in serve/models.toml — add it first")
        return False
    if entry.present:
        return True
    log(f"downloading {model}…")
    return bool(dash_models.download(entry, log, cancel=cancel))


class JobManager:
    """Owns the JobStore + two background workers: one drains benchmark runs (GPU, one at a time), one
    drains downloads (concurrent). Endpoints call enqueue/list/get/cancel."""

    def __init__(self, store: JobStore, manager: ModelManager, *, gateway_url: str,
                 submit=None, download=None, present=None, clock=time.time):
        self.store = store
        self.manager = manager
        self.gateway_url = gateway_url            # the daemon's own base URL (loopback) for --gateway
        self._submit = submit                     # callable(bundle) -> (status:int, detail) or None
        self._download = download or _default_download   # callable(model, log, cancel) -> bool
        self._present_override = present           # callable(model) -> bool (tests inject a stub)
        self._clock = clock
        self._run_wake = asyncio.Event()          # a run was queued, or a download finished (model ready)
        self._dl_wake = asyncio.Event()           # a download was queued
        self._tasks: list[asyncio.Task] = []
        self._current: dict | None = None         # {"id", "proc"} of the running BENCHMARK
        self._cancel_requested: set[str] = set()
        self._pause_requested: set[str] = set()
        self._stop = False

    # --- lifecycle ------------------------------------------------------------------------------

    def start(self) -> None:
        self.store.reap_interrupted()
        self._tasks = [asyncio.create_task(self._run_loop()),
                       asyncio.create_task(self._download_loop())]

    async def aclose(self) -> None:
        self._stop = True
        self._run_wake.set()
        self._dl_wake.set()
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        if self._current and self._current.get("proc"):
            serving.stop(self._current["proc"])

    # --- client-facing API ----------------------------------------------------------------------

    def enqueue(self, spec: dict, *, kind: str = "run") -> str:
        """Queue a run or a download. Enqueuing a run for a model that isn't on disk auto-queues its
        download (on the separate download queue), so "run X" works even when X isn't present yet."""
        jid = self.store.enqueue(spec, kind=kind, now=self._clock())
        if kind == "run":
            model = spec.get("model")
            if model and not self._model_present(model) and not self._download_pending(model):
                self.store.enqueue({"model": model}, kind="download", now=self._clock())
                self._dl_wake.set()
            self._run_wake.set()
        else:
            self._dl_wake.set()
        return jid

    def list(self) -> list[dict]:
        return self.store.list()

    def get(self, jid: str) -> dict | None:
        return self.store.get(jid)

    def cancel(self, jid: str) -> bool:
        """Cancel a queued job (drop it) or a running job (kill its runner / stop its download). False
        if unknown/finished. A running benchmark is cancellable even during the model-load phase."""
        job = self.store.get(jid)
        if job is None:
            return False
        if job["status"] == "queued":
            self.store.update(jid, status="cancelled", finished=self._clock())
            return True
        if job["status"] == "running":
            self._cancel_requested.add(jid)   # downloads poll this; the run worker also kills its proc
            if self._current and self._current["id"] == jid and self._current.get("proc"):
                serving.stop(self._current["proc"])   # kill the runner; worker finalizes as cancelled
            return True
        return False

    def pause(self, jid: str) -> bool:
        """Pause a job. A queued job is set 'paused' (the run scheduler skips it). A running job is
        STOPPED (its runner killed) and set 'paused' — the worker then advances to the next ready job,
        swapping the model. resume() re-queues it (it re-runs from scratch, reloading its model when
        picked). False if unknown/already finished."""
        job = self.store.get(jid)
        if job is None:
            return False
        if job["status"] == "queued":
            self.store.update(jid, status="paused")
            return True
        if job["status"] == "running":
            self._pause_requested.add(jid)
            if self._current and self._current["id"] == jid and self._current.get("proc"):
                serving.stop(self._current["proc"])   # kill the runner; worker finalizes as paused
            return True
        return False

    def resume(self, jid: str) -> bool:
        """Resume a paused job → back to 'queued' (it runs when its turn comes; its model loads then)."""
        job = self.store.get(jid)
        if job is None or job["status"] != "paused":
            return False
        self.store.update(jid, status="queued")
        self._run_wake.set()
        return True

    # --- scheduling -----------------------------------------------------------------------------

    def _model_present(self, model: str | None) -> bool:
        if self._present_override is not None:
            return self._present_override(model)
        e = self.manager.model(model) if model else None   # the manager's registry = what we can serve
        return bool(e and e.present)

    def _download_pending(self, model: str | None) -> bool:
        return any((j["spec"].get("model") == model) for j in self.store.active("download"))

    def _next_ready_run(self) -> dict | None:
        """The oldest queued run whose weights are already present — so the GPU never idles waiting on a
        download. A run whose model is still downloading is left queued; one that's missing with no
        download in flight is failed (nothing will ever make it ready)."""
        for job in self.store.queued("run"):
            model = job["spec"].get("model")
            if self._model_present(model):
                return job
            if not self._download_pending(model):
                self.store.update(job["id"], status="failed", finished=self._clock(),
                                  summary={"note": f"{model}: not downloaded and no download queued"})
        return None

    # --- workers --------------------------------------------------------------------------------

    async def _run_loop(self) -> None:
        while not self._stop:
            job = self._next_ready_run()
            if job is None:
                self._run_wake.clear()
                job = self._next_ready_run()       # re-check after clear so we can't miss a wakeup
                if job is None:
                    await self._run_wake.wait()
                    continue
            await self._run_job(job)

    async def _download_loop(self) -> None:
        while not self._stop:
            job = self.store.next_queued("download")
            if job is None:
                self._dl_wake.clear()
                job = self.store.next_queued("download")
                if job is None:
                    await self._dl_wake.wait()
                    continue
            await self._download_job(job)

    async def _download_job(self, job: dict) -> None:
        jid, spec = job["id"], job["spec"]
        model = spec.get("model")
        out = paths.repo_root() / "results" / f"job-{jid}"
        out.mkdir(parents=True, exist_ok=True)
        logpath = out / "run.log"
        self.store.update(jid, status="running", started=self._clock(), log=str(logpath))

        def log(line: str) -> None:
            with open(logpath, "a") as f:
                f.write(line + "\n")

        ok = False
        try:
            ok = await asyncio.to_thread(self._download, model, log,
                                         lambda: jid in self._cancel_requested)
        except Exception as e:  # noqa: BLE001
            log(f"!! download error: {e}")
        if jid in self._cancel_requested:
            self._cancel_requested.discard(jid)
            self.store.update(jid, status="cancelled", finished=self._clock())
            return
        self.store.update(jid, status="done" if ok else "failed", finished=self._clock(),
                          summary={"note": "downloaded" if ok else "download failed"})
        if ok:
            self._run_wake.set()       # a model just became ready — let the run worker reconsider

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

        if jid in self._pause_requested:             # paused while the model was loading
            self._pause_requested.discard(jid)
            self.manager.unpin()
            self.store.update(jid, status="paused")
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

        if jid in self._pause_requested:             # paused mid-run → re-runnable, not a failure
            self._pause_requested.discard(jid)
            self.store.update(jid, status="paused")
            return
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

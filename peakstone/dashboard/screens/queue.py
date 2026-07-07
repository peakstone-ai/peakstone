"""The daemon queue screen: jobs, live status, and queue management keys."""
from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from ..ui import _fmt_dur
from .reproduce import ReproduceScreen

class QueueScreen(ModalScreen):
    """The daemon's queues, live: the running benchmark, runs waiting behind it, and the separate
    download queue. Cancel any job, or open the live view of the running one."""
    CSS = """
    QueueScreen { align: center middle; }
    #queue { width: 90; height: 26; border: thick $accent; background: $surface; padding: 1; }
    #q-tbl { height: 1fr; }
    #q-note { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("enter", "view", "View running"),
                ("p", "pause", "Pause/resume"), ("x", "cancel", "Cancel"), ("c", "clear", "Clear queued"),
                ("d", "restart_daemon", "Restart daemon")]

    _MARK = {"running": "▶", "queued": "·", "paused": "⏸", "done": "✓", "failed": "✗",
             "cancelled": "∅", "interrupted": "⚠"}

    def compose(self) -> ComposeResult:
        with Vertical(id="queue"):
            yield Static("[b]Daemon queues[/b]  ·  ⏎ view  ·  p pause/resume  ·  x cancel  ·  c clear"
                         "  ·  d restart daemon  ·  Esc close")
            yield DataTable(id="q-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("", id="q-note")

    def action_restart_daemon(self) -> None:
        """Graceful stop + fresh detached start. The daemon-owned queue survives: an interrupted
        running job re-queues on start (R19), so this is the safe lever after daemon-code updates
        or a wedged gateway — no more pkill + hand-restart."""
        self.notify("restarting the daemon…")

        def work() -> None:
            from peakstone.gateway import launch
            ok = launch.restart_daemon()
            self.app.call_from_thread(
                self.notify,
                "daemon restarted — queue resumes" if ok
                else "daemon restart FAILED (see results/gateway.log)",
                severity="information" if ok else "error")

        self.run_worker(work, thread=True)

    def on_mount(self) -> None:
        self.query_one("#q-tbl", DataTable).add_columns("Queue", "Status", "Model", "Scope", "Time")
        self._sig = None
        self._map: list = []     # row -> ("active", None) | ("daemon", job_id)
        self.refill()
        self.app._refresh_daemon_jobs()                 # freshen the app's snapshot now
        self.set_interval(1.5, self._tick)              # rebuild when the snapshot changes
        self.set_interval(2.0, self.app._refresh_daemon_jobs)   # keep the daemon snapshot fresh

    @staticmethod
    def _job_scope(job: dict) -> str:
        spec = job.get("spec") or {}
        if spec.get("level"):
            return f"level {spec['level']}"
        if spec.get("ids"):
            return f"{len(spec['ids'])} challenges"
        s = job.get("summary") or {}
        if s.get("total"):
            return f"{s.get('passed', '')}/{s.get('total', '')}"
        return s.get("note", "") if s else ""

    def _signature(self):
        app = self.app
        dmn = tuple((j.get("id"), j.get("status"), j.get("kind", "run")) for j in app._daemon_jobs)
        return (app.run_active, app._run_spec and app._run_spec["name"], app._run_job_id, dmn)

    @staticmethod
    def _job_time(job: dict) -> str:
        """Elapsed for a running job (live), or total duration for a finished one; '' while queued."""
        st, fin = job.get("started"), job.get("finished")
        if job.get("status") == "running" and st:
            return _fmt_dur(time.time() - st)
        if st and fin:
            return _fmt_dur(fin - st)
        return ""

    def _tick(self) -> None:
        # rebuild on any change, AND every tick while a job runs so its elapsed time ticks up live
        running = any(j.get("status") == "running" for j in self.app._daemon_jobs)
        if running or self._signature() != self._sig:
            self.refill()

    def _add(self, t, label: str, job: dict) -> None:
        t.add_row(label, self._MARK.get(job.get("status"), "?"),
                  (job.get("spec") or {}).get("model", "?"), self._job_scope(job), self._job_time(job))
        self._map.append(("daemon", job["id"]))

    def refill(self) -> None:
        t = self.query_one("#q-tbl", DataTable)
        cur = t.cursor_row
        t.clear()
        self._map = []
        app = self.app
        jobs = list(app._daemon_jobs)
        runs = [j for j in jobs if j.get("kind", "run") == "run"]
        dls = [j for j in jobs if j.get("kind") == "download"]
        # The benchmark we're actively mirroring — shown from local state so it stays visible even if
        # the snapshot momentarily omits it.
        if app.run_active and app._run_spec and app._run_job_id is None:
            t.add_row("run", "▶", app._run_spec["name"], "running", "")
            self._map.append(("active", None))
        # Run queue: the running benchmark, then those waiting behind it (incl. paused, which the
        # scheduler skips but stays visible/resumable). GPU runs one at a time.
        for j in sorted((r for r in runs if r.get("status") in ("running", "queued", "paused")),
                        key=lambda j: (j.get("status") != "running", j.get("created") or 0)):
            self._add(t, "run", j)
        # Download queue: separate + concurrent.
        for j in sorted((d for d in dls if d.get("status") in ("running", "queued", "paused")),
                        key=lambda j: (j.get("status") != "running", j.get("created") or 0)):
            self._add(t, "⬇ dl", j)
        # A few most-recent finished jobs for context (either queue).
        done = [j for j in jobs if j.get("status") in ("done", "failed", "cancelled", "interrupted")]
        for j in sorted(done, key=lambda j: j.get("finished") or 0, reverse=True)[:6]:
            self._add(t, "⬇ dl" if j.get("kind") == "download" else "run", j)
        if not self._map:
            t.add_row("", "idle", "(nothing queued)", "", "")
        else:
            t.move_cursor(row=min(cur or 0, len(self._map) - 1))
        self._sig = self._signature()
        n_rq = sum(1 for j in runs if j.get("status") == "queued")
        n_dl = sum(1 for j in dls if j.get("status") in ("queued", "running"))
        n_r = sum(1 for j in runs if j.get("status") == "running")
        self.query_one("#q-note", Static).update(
            f"[b]{n_rq}[/] runs queued" + (f"  ·  {n_r} running" if n_r else "")
            + (f"  ·  [b]{n_dl}[/] downloads" if n_dl else ""))

    def _selected(self):
        t = self.query_one("#q-tbl", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self._map):
            return None, None
        return self._map[t.cursor_row]

    def action_cancel(self) -> None:
        kind, ref = self._selected()
        if kind == "active" or (kind == "daemon" and ref == self.app._run_job_id):
            self.app.cancel_active()              # the one we're mirroring → stop mirror + kill daemon job
        elif kind == "daemon":
            if self.app.cancel_daemon_job(ref):
                self.notify("cancelled")
        self.app._refresh_daemon_jobs()
        self.refill()

    def action_pause(self) -> None:
        """Toggle pause/resume on the selected job. A paused queued job is skipped by the scheduler; a
        paused running job is stopped and re-runs on resume (reloading its model)."""
        kind, ref = self._selected()
        if kind != "daemon":
            self.notify("select a queued/running/paused job")
            return
        job = next((j for j in self.app._daemon_jobs if j.get("id") == ref), None)
        st = job.get("status") if job else None
        if st == "paused":
            self.notify("resumed" if self.app.resume_daemon_job(ref) else "couldn't resume")
        elif st in ("queued", "running"):
            self.notify("paused" if self.app.pause_daemon_job(ref) else "couldn't pause")
        else:
            self.notify("only queued/running/paused jobs can be paused")
            return
        self.app._refresh_daemon_jobs()
        self.refill()

    def action_clear(self) -> None:
        n = self.app.clear_queued()
        self.notify(f"cancelled {n} queued job(s)" if n else "nothing queued")
        self.app._refresh_daemon_jobs()
        self.refill()

    def on_data_table_row_selected(self, _event) -> None:
        self.action_view()          # ⏎ on a row: the DataTable consumes enter, so route it here

    def action_view(self) -> None:
        if self.app.run_active or self.app._run_result is not None:
            self.app.push_screen(ReproduceScreen())
        else:
            self.notify("no run is being mirrored")


"""Peakstone dashboard (Textual TUI) — live local hardware + a leaderboard browser auto-filtered to
what fits your GPU, so you can see how models that run on YOUR hardware compare (and at what TPS).

Run:  peakstone            (or)  python -m dashboard  [--api URL]
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Footer, Static

from peakstone.engine import levels as eng_levels
from peakstone.engine import paths as eng_paths
from peakstone.engine import versions as eng_versions

from . import challenges as ch_browse
from . import client, hardware, history, localboard, reproduce

# The shared UI vocabulary and the modal screens live in ui.py and screens/ (split out of this
# ~2900-line file — review R21). Everything is re-exported here so existing imports (tests,
# muscle memory) keep working — same convention as the engine's streamproto/handlers re-exports.
from .ui import (CTX_CHOICES, GEN_ATTEMPT, GEN_MARK, GEN_NL, GEN_PHASE,  # noqa: F401
                 REPRODUCE_IDS, _RUN_LOG_MAX, BoardTree, HardwarePanel, ModelTree, NavTree,
                 _bar, _ctx_k, _fmt, _fmt_dur, _hw, _mem, _meter, _model_detail, _model_says,
                 _parse_result, _pretty_progress, _short_cpu, _short_gpu, _think_label)
from .screens import (AddModelScreen, AddWishlistScreen, BudgetScreen,  # noqa: F401
                      ChallengesScreen, ConfirmScreen, CtxScreen, ModelsScreen, PreflightScreen,
                      QuantScreen, QueueScreen, ReasoningScreen, ReproduceScreen, SolutionScreen,
                      UpdateScreen, WishlistScreen, _solution_body, run_with_preflight)

class Dashboard(App):
    CSS = """
    HardwarePanel { height: auto; border: round $accent; padding: 0 1; margin: 0 1; }
    #sortbar { height: 1; margin: 0 1; padding: 0 1; background: $panel; color: $foreground; }
    DataTable { height: 1fr; margin: 0 1; }
    #board { height: 1fr; margin: 0 1; }
    #detail { height: auto; border: round $accent; padding: 0 1; margin: 0 1; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("f", "toggle_fit", "Fit filter"),
        ("s", "cycle_sort", "Sort axis"),
        ("a", "toggle_suites", "All suites"),
        ("S", "submit_local", "Submit run"),
        ("c", "challenges", "Challenges"),
        ("v", "quants", "Quants"),
        ("m", "models", "Models"),
        ("u", "queue", "Queue"),
        ("w", "wishlist", "Wishlist"),
        ("l", "link", "Link GitHub"),
    ]
    SORTS = ["held_out_score", "code_score", "math_score", "self_verify_accuracy", "recovery_rate",
             "agent_score", "planner_score", "tok_per_s", "total_time_s", "score_per_1k_tokens",
             "long_ctx_score", "truncation_rate"]

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.fit = True          # filter to models that fit my VRAM
        self.all_suites = False  # board scopes to the official standard suite; 'a' widens to all
        self._board_scoped = True   # whether the current board is the default-suite subset (sortbar hint)
        self._board_status: str | None = None   # offline / loading banner text
        self.sort_i = 0
        self._board_rows: list[dict] = []
        self._account_label = ""   # right side of the sort bar: @handle when the signing key is linked
        self._version = eng_versions.pkg_version()   # shown on the sort bar (aids version-mismatch debugging)
        # challenges chosen in the Challenges screen; empty = use the quick default repro set.
        self.selected_ids: list[str] = []
        # set when the selection came from a level shortcut (1-5) — runs via --level so the level's
        # judge/agent/prebuilt settings apply; None for a hand-picked selection (plain id run).
        self.selected_level: str | None = None
        # chosen context window, per model name; "" is the global default applied to models without
        # their own override (None at any key = the model's native ctx).
        self.ctx_overrides: dict[str, int | None] = {}
        # chosen reasoning budget per model name ("" = global default); value None=default | "on" | "off"
        # | a positive int (cap thinking at N tokens, then force the answer)
        self.reasoning_overrides: dict[str, str | int | None] = {}
        # chosen generation token budget (max_tokens) per model name ("" = global default; None = engine
        # default). Smaller measures efficiency-at-task; larger gives reasoners room not to be truncated.
        self.budget_overrides: dict[str, int | None] = {}
        # run manager: the daemon (peakstone serve) owns the run queue, the download queue, and serving.
        # This app is a thin FRONTEND — it enqueues jobs and MIRRORS whatever the daemon is currently
        # running into the live view, so runs survive quitting the TUI. _daemon_jobs is the last-polled
        # snapshot of the daemon's queues; run_active means "we're mirroring the running benchmark".
        self.run_active = False
        self._daemon_jobs: list = []
        self._published_tps_by_model: dict[str, float | None] = {}   # for an adopted run's result line
        self._run_lock = threading.Lock()      # guards queue + run-state across the worker and UI threads
        self._run_log: deque = deque(maxlen=_RUN_LOG_MAX)  # bounded ring of streamed lines (viewer replay)
        self._run_log_n = 0                    # monotonic count of lines emitted this run (viewer cursor)
        self._run_result = None
        self._run_spec: dict | None = None
        self._run_submitted: bool | None = None  # None=not yet, True/False=auto-submit outcome
        self._viewer = None                    # the ReproduceScreen currently viewing the active run
        self._run_procs: list = []             # local download subprocesses (for cancel)
        self._run_job_id: str | None = None    # the active daemon job id (benchmark runs)
        self._run_cancelled = False
        self._run_phase: str | None = None     # None | "download" | "run" — for the global status line
        self._run_done = self._run_total = 0   # coverage of the active run
        self._run_t0: float | None = None       # monotonic at first solve (elapsed / sol-s)
        self._run_tps: float | None = None       # most recent challenge's tok/s (live throughput)
        self._run_gen_phase: str | None = None   # "thinking" | "answering" — the model's live channel
        self._dl_done = self._dl_total = 0      # bytes of the active download
        self._corpus = None                     # cached local peakstone corpus (coverage + spec lookup)

    def corpus(self) -> list:
        """Local peakstone corpus (cached) — for the coverage denominator and challenge spec lookup.
        Only a NON-empty load is cached: if the corpus was momentarily unavailable at first access
        (e.g. mid-`corpus sync`, or a checkout that appeared later), retry rather than getting stuck
        showing every challenge under 'other'."""
        if not self._corpus:
            try:
                self._corpus = ch_browse.load_corpus()
            except Exception:  # noqa: BLE001
                self._corpus = []
        return self._corpus

    def corpus_total(self) -> int:
        return len(self.corpus())

    def challenge_spec(self, challenge_id: str) -> str | None:
        return next((c.spec for c in self.corpus() if c.id == challenge_id), None)

    def _ensure_gateway(self) -> None:
        try:
            from peakstone.gateway.launch import ensure_running
            ensure_running()                       # daemon owns the queues + serving; bring it up
        except Exception:  # noqa: BLE001
            pass

    def start_run(self, name: str, *, published_tps=None, challenge_ids=None, level=None,
                  ctx=None, reasoning=None, budget=None, download_only=False):
        """Enqueue a benchmark on the DAEMON's run queue (the single source of truth) and return its
        job id (None if the daemon is unreachable). The daemon serializes runs on the GPU and
        auto-downloads a missing model first; this app just mirrors whatever it's running."""
        if download_only:
            return self.start_download(name)
        self._ensure_gateway()
        spec = {"model": name}
        for k, v in (("ids", challenge_ids), ("level", level), ("ctx", ctx),
                     ("reasoning", reasoning), ("budget", budget)):
            if v is not None:
                spec[k] = v
        try:
            jid = client.enqueue_job(spec, kind="run")
        except client.APIError as e:
            self.notify(f"gateway unreachable: {e}")
            return None
        self._published_tps_by_model[name] = published_tps
        self.notify(f"queued {name}")
        self._refresh_daemon_jobs()                # pick it up (adopt + mirror) promptly
        return jid

    def start_download(self, name: str):
        """Enqueue a model download on the daemon's SEPARATE (concurrent) download queue. Returns the
        job id, or None if the daemon is unreachable."""
        self._ensure_gateway()
        try:
            jid = client.download_model(name)
        except client.APIError as e:
            self.notify(f"gateway unreachable: {e}")
            return None
        self.notify(f"queued download: {name}")
        self._refresh_daemon_jobs()
        return jid

    def _begin_run_locked(self, spec: dict) -> None:
        """Reset the active-run state for `spec`. MUST hold self._run_lock (called from the mirror
        worker when it adopts the daemon's running benchmark)."""
        self.run_active = True
        self._run_spec, self._run_result, self._run_submitted = spec, None, None
        self._run_log, self._run_log_n = deque(maxlen=_RUN_LOG_MAX), 0
        self._run_procs, self._run_cancelled = [], False
        self._run_phase, self._run_done, self._run_total, self._run_t0 = "start", 0, 0, None
        self._run_tps = None
        self._run_gen_phase = None        # "thinking" | "answering" — the model's live channel
        self._dl_done = self._dl_total = 0

    def _daemon_running_job(self) -> dict | None:
        """The benchmark the daemon is currently running, from the last poll snapshot (None if idle)."""
        return next((j for j in self._daemon_jobs
                     if j.get("status") == "running" and j.get("kind", "run") == "run"), None)

    @work(thread=True, exclusive=True, group="daemon-poll")
    def _refresh_daemon_jobs(self) -> None:
        """Poll the daemon's queues into self._daemon_jobs (read by the overview, status bar, and queue
        screen), then — if we're idle and the daemon is running a benchmark — start the mirror loop so
        its live output shows here. This is the ONE place run state enters the TUI."""
        try:
            self._daemon_jobs = client.list_jobs(timeout=3)
        except client.APIError:
            self._daemon_jobs = []
        with self._run_lock:
            idle = not self.run_active
        if idle and self._daemon_running_job() is not None:
            self._mirror_loop()

    @work(thread=True, exclusive=True, group="run")
    def _mirror_loop(self) -> None:
        """Mirror the daemon's running benchmark into the live view, then move on to the next one. All
        run logic lives in the daemon; this only streams its log + shows the finished result."""
        while True:
            job = self._daemon_running_job()
            if job is None:
                with self._run_lock:
                    self.run_active, self._run_phase = False, None
                return
            jspec = job.get("spec") or {}
            name = jspec.get("model", "?")
            spec = {"name": name, "published_tps": self._published_tps_by_model.get(name),
                    "level": jspec.get("level"), "download_only": False}
            with self._run_lock:
                self._begin_run_locked(spec)
            self.call_from_thread(self._viewer_reset)
            res = self._mirror_job(job["id"], name, spec["published_tps"])
            history.append({"model": res.model, "ok": res.ok, "your_tps": res.your_tps,
                            "published_tps": res.published_tps, "code_score": res.code_score, "note": res.note})
            self._run_result = res
            self.call_from_thread(self._viewer_show, res)
            if res.ok and self._run_submitted and not self._run_cancelled:  # the daemon auto-submits
                self.call_from_thread(self.notify, f"{name}: submitted ✓")
                self.call_from_thread(self.load_board)        # pull the new result into the leaderboard
            try:                                # refresh so the loop sees the now-finished status
                self._daemon_jobs = client.list_jobs(timeout=3)
            except client.APIError:
                pass

    def _mirror_job(self, jid: str, name: str, published_tps):
        """Stream a daemon job's log into the run viewer and build its result. Used both for runs this
        TUI enqueued and for ones it adopted (CLI-launched). Dropping the stream never stops the run."""
        gw = client.GATEWAY_DEFAULT
        with self._run_lock:
            self._run_job_id = jid
        try:
            for line in client.stream_job_log(jid, base_url=gw):
                if self._run_cancelled:
                    break
                self._run_emit(line)
        except client.APIError as e:
            self._run_emit(f"!! lost log stream (run continues in the daemon): {e}")
        job = None
        try:
            job = client.get_job(jid, base_url=gw)
        except client.APIError:
            pass
        with self._run_lock:
            self._run_job_id = None
        if self._run_cancelled:
            return reproduce.ReproduceResult(name, False, published_tps=published_tps,
                                             note="cancelled")
        if not job:
            return reproduce.ReproduceResult(name, False, published_tps=published_tps,
                                             note="job not found")
        summary = job.get("summary") or {}
        self._run_submitted = summary.get("submitted")
        # Fetch the job's bundle from the DAEMON over HTTP (works against a remote gateway too —
        # review R21: reading it off local disk silently broke off-host); disk is the fallback.
        bundle = None
        try:
            bundle = client.get_job_bundle(jid)
        except client.APIError:
            pass
        if bundle is None:
            bpath = eng_paths.repo_root() / "results" / f"job-{jid}" / "bundle.json"
            try:
                if bpath.exists():
                    bundle = json.loads(bpath.read_text())
            except (OSError, ValueError):
                pass
        note = job.get("status") or "?"
        if summary.get("run_status") == "not_capable":   # non-viable config — surface the verdict
            cats = ", ".join(summary.get("abandoned_categories") or []) or "every category"
            note = f"not capable — repetition loops ({cats})"
        return reproduce.ReproduceResult(
            name, job.get("status") == "done", your_tps=summary.get("your_tps"),
            published_tps=published_tps, code_score=summary.get("code_score"),
            passed=summary.get("passed", 0), total=summary.get("total", 0),
            note=note, bundle=bundle)

    def _dl_progress(self, done, total) -> None:
        with self._run_lock:
            self._dl_done, self._dl_total = done or 0, total or 0
        if self._viewer is not None:          # drive the viewer's bar between log lines (~every 0.5s)
            self.call_from_thread(self._viewer._update_stat)

    def _run_emit(self, line: str) -> None:
        # Runs on the bench reader thread — it must NEVER block, or the runner's stdout pipe fills and
        # the whole run deadlocks (a blocking call_from_thread per line was the prior bug). So just
        # buffer (deque.append is atomic); the viewer drains this ring on its own UI-thread timer
        # (ReproduceScreen._drain_log), coalescing under a flood. No call_from_thread here.
        self._run_log.append(line)
        self._run_log_n += 1
        self._track(line)

    def _track(self, line: str) -> None:
        """Single source of truth for the active run's phase + coverage (read by the global overview AND
        the run view), parsed from the stream under the lock."""
        if line.startswith(GEN_MARK) or line.startswith(GEN_ATTEMPT):
            return
        if line.startswith(GEN_PHASE):
            with self._run_lock:
                self._run_gen_phase = line[len(GEN_PHASE):]   # "thinking" | "answering"
            return
        with self._run_lock:
            if "downloading" in line.lower():
                self._run_phase = "download"
            elif "→ solving" in line or "benchmarking" in line:
                self._run_phase = "run"
            if "→ solving" in line and self._run_t0 is None:
                self._run_t0 = time.monotonic()
            if "→ solving" in line:
                self._run_gen_phase = None    # new challenge → phase unknown until it streams
            if "→ solving" not in line and " | " in line:
                self._run_done += 1
                self._run_gen_phase = None    # challenge finished → no longer generating
                m = re.search(r"([\d.]+)\s*tok/s", line)   # live throughput from the per-challenge line
                if m:
                    self._run_tps = float(m.group(1))
            else:
                m = re.search(r"over (\d+) challenge", line) or re.search(r":\s*(\d+) challenges", line)
                if m:
                    self._run_total = int(m.group(1))

    def run_progress(self) -> dict:
        """Atomic snapshot of the active run's progress (for the overview + run view)."""
        with self._run_lock:
            snap = {"active": self.run_active, "model": (self._run_spec or {}).get("name", "?"),
                    "phase": self._run_phase, "done": self._run_done, "total": self._run_total,
                    "t0": self._run_t0, "tps": self._run_tps, "gen_phase": self._run_gen_phase,
                    "dl_done": self._dl_done, "dl_total": self._dl_total}
        snap["queued"] = self.queued_count()       # from the daemon snapshot, outside the run lock
        return snap

    def run_status_inline(self) -> str:
        """Concise live status shown right after the model name: phase + tok/s + coverage + queue, e.g.
        "🧠 thinking 48 tok/s  ·  3/200 challenges  ·  2 queued". "" when nothing is being mirrored
        (or it's downloading — that shows on the bottom row instead)."""
        p = self.run_progress()
        if not p["active"] or p.get("phase") == "download":
            return ""
        phase = {"thinking": "[magenta]🧠 thinking[/]",
                 "answering": "[green]✍ answering[/]"}.get(p.get("gen_phase"), "")
        tps = f"{p['tps']:.0f} tok/s" if p.get("tps") else ""
        live = "  ".join(x for x in (phase, tps) if x) or (p.get("phase") or "starting")
        cov = f"{min(p['done'], p['total'])}/{p['total']} challenges" if p["total"] else ""
        q = f"{p['queued']} queued" if p["queued"] else ""
        return "  ·  ".join(x for x in (live, cov, q) if x)

    def job_status(self) -> str:
        """One-line status of the active/queued job for the performance overview (incl. a progress bar)."""
        p = self.run_progress()
        if p["active"]:
            if p["phase"] == "download" and p["dl_total"]:
                queued = f"   ·   {p['queued']} queued" if p["queued"] else ""
                return f"[b]⬇ {p['model']}[/] downloading  {_bar(p['dl_done'], p['dl_total'])}{queued}"
            return ""   # a running benchmark's status (phase·tok/s·coverage·queue) is on the model line
        if p["queued"]:
            return f"[dim]{p['queued']} run(s) queued[/]"
        return ""

    def _viewer_reset(self) -> None:
        if self._viewer is not None:
            self._viewer.reset_view()

    def _viewer_show(self, res) -> None:
        if self._viewer is not None:
            self._viewer.show_result(res)

    def cancel_active(self) -> bool:
        """Cancel the benchmark we're mirroring by telling the daemon to kill it. False if nothing is
        being mirrored. (The daemon's run worker then advances to the next ready run.)"""
        with self._run_lock:
            if not self.run_active:
                self.notify("no active run")
                return False
            self._run_cancelled = True
            jid = self._run_job_id
        if jid:
            try:
                client.cancel_job(jid)             # tell the daemon to kill the benchmark
            except client.APIError:
                pass
        self.notify("cancelling active run…")
        return True

    def shutdown_runs(self) -> None:
        """Called on quit. Stops MIRRORING — but deliberately does NOT cancel the daemon's job: that's
        the whole point of the decoupling, the run keeps going and is re-adopted next launch."""
        with self._run_lock:
            self._run_cancelled = True             # breaks the log-mirroring loop; daemon job lives on

    # queue management (the QueueScreen drives these) — they act on the daemon's queues over HTTP.
    def cancel_daemon_job(self, jid: str) -> bool:
        try:
            return client.cancel_job(jid)
        except client.APIError:
            return False

    def pause_daemon_job(self, jid: str) -> bool:
        try:
            return client.pause_job(jid)
        except client.APIError:   # daemon momentarily unreachable (restart/timeout) — don't crash the TUI
            return False

    def resume_daemon_job(self, jid: str) -> bool:
        try:
            return client.resume_job(jid)
        except client.APIError:
            return False

    def clear_queued(self) -> int:
        """Cancel every queued (not-yet-running) job on the daemon — runs and downloads alike."""
        n = 0
        for j in self._daemon_jobs:
            if j.get("status") == "queued" and self.cancel_daemon_job(j["id"]):
                n += 1
        return n

    def queued_count(self) -> int:
        """Number of queued benchmark runs on the daemon (for the overview / status bar)."""
        return sum(1 for j in self._daemon_jobs
                   if j.get("status") == "queued" and j.get("kind", "run") == "run")

    def compose(self) -> ComposeResult:
        # No app Header — the hardware panel (with the clock) is the top bar; the sort/filter bar sits
        # directly under it and relates to the leaderboard below; the Footer holds the key shortcuts.
        yield HardwarePanel()
        yield Static("", id="sortbar")
        yield BoardTree("leaderboard", id="board")
        yield Static("", id="detail")            # extended stats for the highlighted run (bottom panel)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Peakstone"
        tree = self.query_one("#board", BoardTree)
        tree.show_root = False
        tree.auto_expand = False
        self._update_sortbar()                   # populate the bar immediately (before the board loads)
        self.load_board()
        self._load_account()                     # fill in the linked-account name on the sort bar
        self._check_update()                      # nudge if a newer client is available
        self._autosync_corpus()                   # pip installs: fetch the corpus if missing/stale
        tree.focus()
        # Poll the daemon's queues: adopt+mirror any benchmark it's already running (CLI-launched, or
        # left from a prior session) and keep the snapshot fresh for the overview / status bar / queue.
        self._refresh_daemon_jobs()
        self.set_interval(3.0, self._refresh_daemon_jobs)

    def _update_sortbar(self, max_vram: float | None = None, *, scoped: bool | None = None,
                        status: str | None = "") -> None:
        """The sort/filter bar under the hardware panel — the controls that shape the leaderboard below.
        Shows the active sort axis + the hardware-fit filter (keys live in the Footer: s sort · f fit)."""
        if max_vram is None:
            snap = hardware.snapshot()
            max_vram = snap.max_vram_gb if (self.fit and snap.max_vram_gb) else None
        if scoped is not None:
            self._board_scoped = scoped
        if status != "":            # "" = "keep current"; None/str = set
            self._board_status = status
        self.query_one("#sortbar", Static).update(self._sortbar_renderable(max_vram))

    def _sortbar_renderable(self, max_vram: float | None):
        """One line: sort/hardware controls on the left, the linked account on the right."""
        scope = f"fits ≤{max_vram:g} GB" if max_vram else "all hardware"
        sel = f"   ·   ▶ {len(self.selected_ids)} challenges selected" if self.selected_ids else ""
        suites = "all suites" if self.all_suites or not getattr(self, "_board_scoped", True) else "standard"
        left = (f"[b]sort[/] {self.SORTS[self.sort_i]}   ·   [b]hardware[/] {scope}   ·   "
                f"[b]suite[/] {suites}{sel}")
        st = getattr(self, "_board_status", None)
        if st and st != "loading":
            left += f"   ·   [yellow]{st}[/]"
        from rich.table import Table
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(justify="right")
        acct = f"   {self._account_label}" if self._account_label else ""
        grid.add_row(left, f"[dim]v{self._version}[/]{acct}")
        return grid

    @work(thread=True, exclusive=True, group="account")
    def _load_account(self) -> None:
        """Look up whether this machine's signing key is linked to an account; show it on the sort bar."""
        try:
            from ..engine import keys as eng_keys
            _, pub = eng_keys.load_or_create_keypair()
        except Exception:  # noqa: BLE001
            return
        acct = client.get_account(self.base_url, pub)
        label = (f"[green]@{acct['handle']}[/]" if acct and acct.get("handle")
                 else "[dim]unlinked · l[/]")
        self.call_from_thread(self._set_account, label)

    def _set_account(self, label: str) -> None:
        self._account_label = label
        self._update_sortbar()

    @work(thread=True, exclusive=True, group="update-check")
    def _check_update(self) -> None:
        """On startup, if the client is behind the server's latest/min version, pop up an update
        prompt (recommend + offer to update, default yes). Off with PEAKSTONE_NO_UPDATE_CHECK=1."""
        if os.environ.get("PEAKSTONE_NO_UPDATE_CHECK") in ("1", "true"):
            return
        from ..engine import versions
        info = client.get_version(self.base_url)
        if not info:
            return
        installed = versions.pkg_version()
        if versions.is_outdated(installed, info.get("min_supported")):
            self.call_from_thread(self.push_screen,
                                  UpdateScreen(installed, info["min_supported"], required=True))
        elif versions.is_outdated(installed, info.get("latest")):
            self.call_from_thread(self.push_screen,
                                  UpdateScreen(installed, info["latest"], required=False))

    @work(thread=True, exclusive=True, group="corpus-sync")
    def _autosync_corpus(self) -> None:
        """For pip-installed clients, fetch the challenge corpus from GitHub if it's missing or was
        synced from a different version — so the challenge tree groups correctly instead of dumping
        everything under 'other'. No-op for repo checkouts / explicit PEAKSTONE_CHALLENGES."""
        from . import corpus
        if not corpus.should_autosync():
            return
        self.call_from_thread(self.notify, "fetching the challenge corpus …", timeout=6)
        try:
            n, _ref = corpus.sync(log=lambda *_: None)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"corpus sync failed: {e} — run `peakstone corpus sync`",
                                  severity="warning", timeout=10)
            return
        self._corpus = None                       # invalidate so the self-healing cache reloads it
        self.call_from_thread(self.notify, f"challenge corpus ready ✓ ({n} challenges)", timeout=6)

    def action_link(self) -> None:
        """Link the signing key to a GitHub account — hand off to the browser OAuth flow, then refresh."""
        from .login import login_main
        with self.suspend():
            rc = login_main(["--api", self.base_url])
        self.notify("linked ✓" if rc == 0 else "not linked (cancelled or failed)",
                    severity="information" if rc == 0 else "warning")
        self._load_account()

    def action_refresh(self) -> None:
        self.load_board()

    def action_toggle_fit(self) -> None:
        self.fit = not self.fit
        self._update_sortbar()                   # instant feedback; load_board re-renders the board
        self.load_board()

    def action_cycle_sort(self) -> None:
        self.sort_i = (self.sort_i + 1) % len(self.SORTS)
        self._update_sortbar()                   # instant feedback; load_board re-renders the board
        self.load_board()

    def action_models(self) -> None:
        self.push_screen(ModelsScreen())

    def action_queue(self) -> None:
        self.push_screen(QueueScreen())

    def action_quit(self) -> None:
        """Quitting is safe — the daemon owns the queues + serving, so any run keeps going and is
        re-adopted next launch. Just stop mirroring and exit."""
        self.shutdown_runs()
        self.exit()

    def action_challenges(self) -> None:
        self.push_screen(ChallengesScreen())

    def _cursor_family(self):
        """(family, repo) of the highlighted board node — works on a model node or a quant child."""
        node = self.query_one("#board", BoardTree).cursor_node
        d = (node.data if node else None) or {}
        return d.get("family"), d.get("repo"), d.get("row", {})

    def action_quants(self) -> None:
        fam, repo, _ = self._cursor_family()
        if fam:
            self.push_screen(QuantScreen(fam, self.base_url, repo=repo))

    def action_wishlist(self) -> None:
        on_board = {r.get("family") for r in self._board_rows}
        self.push_screen(WishlistScreen(self.base_url, on_board))

    def run_ids(self) -> list[str]:
        """Challenges to run: the user's Challenges-screen selection, else the quick default set."""
        return self.selected_ids or REPRODUCE_IDS

    def ctx_for(self, name: str) -> int | None:
        """The context window to serve `name` at: its own override, else the global default, else
        None (the model's native ctx)."""
        return self.ctx_overrides.get(name, self.ctx_overrides.get(""))

    def reasoning_for(self, name: str) -> str | None:
        """The reasoning budget to serve `name` with: its own override, else the global default,
        else None (the model's configured budget). 'on' = full thinking, 'off' = no thinking."""
        return self.reasoning_overrides.get(name, self.reasoning_overrides.get(""))

    def budget_for(self, name: str) -> int | None:
        """The generation token budget (max_tokens) for `name`: its own override, else the global
        default, else None (the engine's generous default)."""
        return self.budget_overrides.get(name, self.budget_overrides.get(""))

    def effective_ids(self) -> list[str]:
        """The challenge ids a run will actually cover: a selected level resolves to its set, else
        the explicit selection / default. Used by the ctx picker to count long-context skips."""
        if self.selected_level:
            try:
                _, lvls = eng_levels.load_levels()
                lv = lvls.get(self.selected_level)
                if lv:
                    return eng_levels.resolve(lv, self.corpus())
            except Exception:  # noqa: BLE001
                pass
        return self.run_ids()

    def on_tree_node_expanded(self, ev) -> None:
        d = ev.node.data or {}
        if d.get("kind") == "quant" and not d.get("filled"):   # lazily load this run's per-challenge results
            d["filled"] = True
            run = (d.get("row") or {}).get("run", {})
            self.load_run_results(ev.node, run.get("bundle_hash"), run.get("path") if run.get("local") else None)

    @work(thread=True)
    def load_run_results(self, node, bundle_hash, local_path=None) -> None:
        # a local run reads its own bundle from disk (works offline); fall back to the API when it's
        # a published/server run or the local file can't be read.
        if local_path:
            res = localboard.read_run_results(local_path)
            if res is not None:
                self.call_from_thread(self._add_results, node, res, bundle_hash)
                return
        if not bundle_hash:
            self.call_from_thread(self._add_results, node, [], None)
            return
        try:
            data = client.get_run(self.base_url, bundle_hash)
        except client.APIError:
            self.call_from_thread(self._add_results, node, None, bundle_hash)
            return
        self.call_from_thread(self._add_results, node, data.get("results", []), bundle_hash)

    @staticmethod
    def _result_leaf(r: dict) -> str:
        if r.get("error") == "repetition-loop":
            return f"[magenta]⟳[/] {r.get('challenge', '?'):30} repetition loop"
        final = r.get("final") or 0.0
        mark = "[green]✓[/]" if final >= 0.999 else ("[red]✗[/]" if final == 0 else "[yellow]◐[/]")
        pt = f"  {r['passed']}/{r['total']}" if r.get("total") else ""
        cat = r.get("category") or r.get("verification") or ""
        return f"{mark} {r.get('challenge', '?'):30} {final:.2f}{pt}  [dim]{cat}[/]"

    def _add_results(self, node, results, bundle_hash) -> None:
        if results is None:
            node.add_leaf("[red]could not load results[/]")
            return
        if not results:
            node.add_leaf("[dim](no per-challenge results)[/]")
            return
        # group the run's challenges the same way the challenges window does: collection -> date ->
        # family -> challenge. Challenges we have locally drive the grouping; any others go under "other".
        by_id = {r["challenge"]: r for r in results}
        known = [c for c in self.corpus() if c.id in by_id]

        def grp_label(label, chs):   # name (count) + average score over the group's challenges
            return self._grp_label(label, [by_id[c.id] for c in chs])

        for grp in ch_browse.group_by_collection(known):
            chs = grp["chs"]
            coll = node.add(grp_label(grp["label"], chs))
            if grp["kind"] == "native":
                for bucket, dchs in ch_browse.group_by_date(chs).items():
                    dnode = coll.add(grp_label(bucket, dchs))
                    for fam, fchs in ch_browse.group_by_family(dchs).items():
                        fnode = dnode.add(grp_label(fam, fchs))
                        self._add_result_leaves(fnode, fchs, by_id, bundle_hash)
            else:
                for bucket, dchs in ch_browse.group_by_date(chs).items():
                    dnode = coll.add(grp_label(bucket, dchs))
                    self._add_result_leaves(dnode, dchs, by_id, bundle_hash)
        extra = [by_id[i] for i in by_id if i not in {c.id for c in known}]
        if extra:
            other = node.add(self._grp_label("other", extra))   # ran but not in the local corpus
            for r in extra:
                other.add_leaf(self._result_leaf(r),
                               data={"kind": "result", "row": r, "bundle_hash": bundle_hash})

    @staticmethod
    def _grp_label(label: str, results: list) -> str:
        vals = [r["final"] for r in results if r.get("final") is not None]
        avg = f"   [b]{sum(vals) / len(vals):.2f}[/]" if vals else ""
        return f"{label} ({len(results)}){avg}"

    def _add_result_leaves(self, parent, challenges, by_id, bundle_hash) -> None:
        for c in sorted(challenges, key=lambda c: c.id):
            r = by_id[c.id]
            parent.add_leaf(self._result_leaf(r),
                            data={"kind": "result", "row": r, "bundle_hash": bundle_hash})

    def open_solution(self, d: dict, quant_row: dict | None = None) -> None:
        cid = (d.get("row") or {}).get("challenge", "?")
        qr = quant_row or {}
        run = qr.get("run", {})
        label = _model_says(qr.get("family"), run.get("artifact"), run.get("context"),
                            run.get("reasoning")) if qr else None
        self.push_screen(SolutionScreen(cid, self.challenge_spec(cid), self.base_url,
                                        d.get("bundle_hash"), model_label=label))

    @work(thread=True, exclusive=True)
    def load_board(self) -> None:
        """Offline-first: build the board from LOCAL runs and paint it immediately, then merge in
        the server rows once the API answers. One worker, two renders — no cancellation race."""
        snap = hardware.snapshot()
        max_vram = snap.max_vram_gb if (self.fit and snap.max_vram_gb) else None
        sort = self.SORTS[self.sort_i]
        try:
            local, scoped = localboard.build_local_board(all_suites=self.all_suites)
        except Exception:  # noqa: BLE001 — a broken results dir must never blank the board
            local, scoped = [], True
        # phase 1: local-only, instant
        self.call_from_thread(self._render, localboard.merge_rows(local, [], sort=sort),
                              max_vram, scoped, "loading")
        # phase 2: pull the server board and merge (collapse=quant → every quant run)
        try:
            data = client.get_leaderboard(self.base_url, max_vram_gb=max_vram,
                                           sort=sort, collapse="quant")
        except client.APIError as e:
            if not local:
                self.call_from_thread(self._render_error, str(e))
            else:
                self.call_from_thread(self._render, localboard.merge_rows(local, [], sort=sort),
                                      max_vram, scoped, f"offline · local runs only ({str(e)[:40]})")
            return
        merged = localboard.merge_rows(local, data.get("leaderboard", []), sort=sort)
        self.call_from_thread(self._render, merged, max_vram, scoped, None)

    def _quant_label(self, r: dict) -> str:
        """Key numbers only — the full per-run stats live in the bottom detail panel (highlight to see)."""
        run = r.get("run", {})
        cov = f"{r['n_total']}/{self.corpus_total()}" if r.get("n_total") else "—"
        tag = "⌂ " if run.get("local") and not run.get("published") else ""
        pub = "  [green]✓ pub[/]" if (run.get("published") or run.get("submitted")) else ""
        return (f"{tag}{run.get('artifact', '—'):16} "
                f"held-out {_fmt(r.get('held_out_score'))}  code {_fmt(r.get('code_score'))}  "
                f"{_fmt(r.get('tok_per_s'), '{:.0f}')} tps  cov {cov}{pub}")

    def _render(self, rows: list[dict], max_vram: float | None,
                scoped: bool = True, status: str | None = "") -> None:
        tree = self.query_one("#board", BoardTree)
        # preserve the cursor across the two-phase (local → merged) re-render
        prev = None
        cur = tree.cursor_node
        if cur is not None and cur.data:
            cd = cur.data
            prev = (cd.get("family"), (cd.get("row") or {}).get("run", {}).get("bundle_hash"))
        tree.clear()
        self._update_sortbar(max_vram, scoped=scoped, status=status)
        self._board_rows = rows
        restore_line = 0
        line = 0
        fams: dict[str, list] = {}
        for r in rows:                                   # rows arrive sorted; group preserving order
            fams.setdefault(r.get("family", "?"), []).append(r)
        for rank, (fam, frows) in enumerate(fams.items(), 1):
            best = frows[0]
            repo = best.get("run", {}).get("hf_repo")
            all_local = all(fr.get("run", {}).get("local") and not fr.get("run", {}).get("published")
                            for fr in frows)
            node = tree.root.add(
                f"[b]{'⌂ ' if all_local else ''}{rank}. {fam}[/]   held-out {_fmt(best.get('held_out_score'))}   "
                f"code {_fmt(best.get('code_score'))}   {len(frows)} quant(s)",
                data={"kind": "family", "family": fam, "repo": repo, "row": best})
            line += 1
            for r in frows:   # expandable: drill in to see the per-challenge results of that run
                if prev and prev == (fam, r.get("run", {}).get("bundle_hash")):
                    restore_line = line
                node.add(self._quant_label(r),
                         data={"kind": "quant", "family": fam, "row": r, "filled": False,
                               "repo": r.get("run", {}).get("hf_repo")})
                line += 1
        if not rows:
            tree.root.add_leaf("(no local or server runs yet)")
        if tree.root.children:
            tree.cursor_line = restore_line
        self._update_detail(tree.cursor_node)            # populate the bottom panel for the first row

    def _update_detail(self, node) -> None:
        self.query_one("#detail", Static).update(self._detail_text((node.data if node else None) or {}))

    def _detail_text(self, d: dict) -> str:
        """The bottom panel: the full stats for the highlighted run (family/quant) — everything the
        board rows no longer show — or a one-line summary for a per-challenge result leaf."""
        r = d.get("row")
        if d.get("kind") == "result" and r:
            cat = r.get("category") or r.get("verification") or ""
            pt = f"  {r['passed']}/{r['total']} tests" if r.get("total") else ""
            return f"[b]{r.get('challenge', '?')}[/]  final {r.get('final', 0):.2f}{pt}  [dim]{cat}[/]"
        if not r or "run" not in r:
            return "[dim]highlight a model for its full stats[/]"
        run = r.get("run", {})
        cov = f"{r['n_total']}/{self.corpus_total()}" if r.get("n_total") else "—"
        ctxw = f" [yellow]⚠{r['n_ctx_limited']}[/]" if r.get("n_ctx_limited") else ""   # runs that hit the ctx limit
        mem = _mem(run.get("vram_used_gb") or run.get("vram_gb"), run.get("ram_used_gb") or run.get("ram_gb"))
        hw = _hw(run)
        head = (f"[b]{r.get('family')}[/] · {run.get('artifact', '—')} · {_ctx_k(run.get('context'))} ctx"
                + (f" · think {run['reasoning']}" if run.get("reasoning") else "")
                + (f" · {(run.get('trust_tier') or '').replace('-', ' ')}" if run.get("trust_tier") else ""))
        scores = (f"held-out [b]{_fmt(r.get('held_out_score'))}[/]  code {_fmt(r.get('code_score'))}  "
                  f"math {_fmt(r.get('math_score'))}  agentic {_fmt(r.get('agent_score'))}  "
                  f"planner {_fmt(r.get('planner_score'))}  long-ctx {_fmt(r.get('long_ctx_score'))}  "
                  f"safety {_fmt(r.get('safety_score'))}")
        meta = (f"calibration {_fmt(r.get('self_verify_accuracy'))} (conf {_fmt(r.get('confidence_score'))})  ·  "
                f"self-repair {_fmt(r.get('recovery_rate'))}  ·  truncation {_fmt(r.get('truncation_rate'))}")
        perf = (f"{_fmt(r.get('tok_per_s'), '{:.0f}')} tok/s · {_fmt(r.get('sol_per_s'), '{:.2f}')} sol/s · "
                f"{_fmt_dur(r.get('total_time_s'))} · {_fmt(r.get('score_per_1k_tokens'), '{:.2f}')}/1k tok · "
                f"{mem} used · cov {cov}{ctxw}" + (f" · [dim]{hw}[/]" if hw else ""))
        lines = [head, scores, meta, perf]
        if run.get("local"):     # provenance for a local run: where it lives + whether it's on the board
            sub = ("[green]submitted ✓[/]" if run.get("published") or run.get("submitted")
                   else "[yellow]not submitted — press S to publish[/]")
            lines.append(f"[dim]local · {run.get('path', '?')} · {run.get('suite', '?')}[/] · {sub}")
        return "\n".join(lines)

    def on_tree_node_highlighted(self, event) -> None:
        if getattr(event, "control", None) is not None and event.control.id == "board":
            self._update_detail(event.node)

    def _render_error(self, msg: str) -> None:
        tree = self.query_one("#board", BoardTree)
        tree.clear()
        self.sub_title = f"{self.base_url}  ·  API unreachable · no local runs"
        tree.root.add_leaf(f"API unreachable — {msg[:60]}")
        tree.root.add_leaf("[dim]run a benchmark (v · quants) to build a local board[/]")

    def action_toggle_suites(self) -> None:
        self.all_suites = not self.all_suites
        self._update_sortbar()
        self.load_board()

    def action_submit_local(self) -> None:
        """Publish the highlighted local run's bundle to the server (the offline board's on-ramp
        to the shared leaderboard)."""
        node = self.query_one("#board", BoardTree).cursor_node
        run = ((node.data or {}).get("row") or {}).get("run", {}) if node else {}
        if not run.get("local") or run.get("no_bundle"):
            self.notify("Highlight a local run with a bundle to submit.", severity="warning")
            return
        if run.get("published") or run.get("submitted"):
            self.notify("That run is already published.", severity="information")
            return
        self._submit_local(run.get("path"))

    @work(thread=True)
    def _submit_local(self, run_dir) -> None:
        import json as _json
        from pathlib import Path as _Path
        bpath = None
        for name in ("bundle.json", "combined.bundle.json"):
            p = _Path(run_dir or "") / name
            if p.is_file():
                bpath = p
                break
        if bpath is None:
            self.call_from_thread(self.notify, "No bundle.json found for that run.", severity="error")
            return
        try:
            bundle = _json.loads(bpath.read_text())
            status, detail = client.submit_bundle(self.base_url, bundle)
        except client.APIError as e:
            self.call_from_thread(self.notify, f"Submit failed: {e}", severity="error")
            return
        except (OSError, ValueError) as e:
            self.call_from_thread(self.notify, f"Bad bundle: {e}", severity="error")
            return
        msg = ("submitted ✓" if status == 201 else "already on the server ✓" if status == 409
               else f"rejected ({status}): {detail[:80]}")
        sev = "information" if status in (201, 409) else "error"
        self.call_from_thread(self.notify, msg, severity=sev)
        if status in (201, 409):
            self.call_from_thread(self.load_board)


def main() -> None:
    import argparse
    import sys

    # `peakstone serve …` runs the standing model-swapping OpenAI gateway; `peakstone jobs …` drives
    # its benchmark queue headless. Both own their argparsers. Bare `peakstone` launches the TUI.
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from peakstone.gateway.__main__ import main as serve_main
        sys.exit(serve_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "jobs":
        from peakstone.gateway.__main__ import jobs_main
        sys.exit(jobs_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        from peakstone.dashboard.login import login_main   # link the signing key to a GitHub account
        sys.exit(login_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("update", "--update"):
        from peakstone.dashboard.update import update_main   # upgrade the client (pipx/pip)
        sys.exit(update_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "corpus":
        from peakstone.dashboard.corpus import corpus_main   # fetch the challenge corpus from GitHub
        sys.exit(corpus_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("bench", "run"):
        from peakstone.engine.runner import main as bench_main   # the eval CLI, unified under `peakstone`
        sys.exit(bench_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        from peakstone.engine.check import check_main   # CI regression gate: bundle vs baseline bundle
        sys.exit(check_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "reveal":
        from peakstone.engine.private import reveal_main   # open a private challenge's commitment
        sys.exit(reveal_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "submit":
        from peakstone.dashboard.submit import submit_main   # POST a signed bundle to the board
        sys.exit(submit_main(sys.argv[2:]))

    ap = argparse.ArgumentParser(prog="peakstone", description="Peakstone hardware dashboard")
    ap.add_argument("--version", action="version", version=f"peakstone {eng_versions.pkg_version()}")
    ap.add_argument("--api", default=client.API_DEFAULT, help="Peakstone API base URL")
    ap.add_argument("--no-gateway", action="store_true",
                    help="don't auto-spawn the local model gateway (peakstone serve) on startup")
    args = ap.parse_args()

    # Bring up the standing model gateway (detached) so a local OpenAI endpoint is available while
    # the dashboard runs — and keeps running after it quits. Best-effort: never block launching the
    # TUI on it. Disable with --no-gateway or PEAKSTONE_NO_GATEWAY=1.
    if not args.no_gateway and os.environ.get("PEAKSTONE_NO_GATEWAY") not in ("1", "true"):
        try:
            from peakstone.gateway.app import load_gateway_config
            from peakstone.gateway.launch import ensure_running
            g = load_gateway_config()
            ensure_running(g["host"], g["port"], g["idle_timeout_s"], wait=0)
        except Exception:  # noqa: BLE001
            pass   # the gateway is a convenience here in Phase 1; the TUI works without it

    Dashboard(args.api).run()


if __name__ == "__main__":
    main()

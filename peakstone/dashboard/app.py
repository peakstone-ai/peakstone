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
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static, Tree
from rich.console import Group
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from peakstone.engine import capabilities as eng_caps
from peakstone.engine import levels as eng_levels
from peakstone.engine import paths as eng_paths
from peakstone.engine import versions as eng_versions

from . import challenges as ch_browse
from . import client, hardware, history, localboard, models, preflight, reproduce, wishlist

# a short, fast challenge set for a reproduce run — enough to measure tok/s + a code score
REPRODUCE_IDS = ["py-02-csv-groupby", "py-05-calc", "py-01-fizzbuzz"]


def _bar(used: int, total: int, width: int = 22) -> str:
    frac = (used / total) if total else 0.0
    filled = int(frac * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {used:,}/{total:,}"


def _meter(label: str, used: int, total: int) -> str:
    """'LABEL [bar] used/total MiB' padded to a fixed width so the GPU/CPU id printed after it lines
    up across rows regardless of how many digits the byte counts have."""
    return f"{label} {_bar(used, total, 16)} MiB".ljust(44)


def _model_detail(lm: dict) -> str:
    """Right-corner one-liner for a served model: '▶ <name>  <ctx> · <quant> · think <x>'."""
    parts = lm["file"].replace("\\", "/").split("/")
    nm = parts[-2] if len(parts) >= 2 else parts[-1]   # models/<name>/file.gguf -> <name>
    q = models.quant_label(parts[-1])
    rb = lm.get("reasoning")               # the served --reasoning-budget value (string from the cmdline)
    if rb is None:
        think = None
    elif rb == "0":
        think = "off"
    elif rb == "-1":
        think = "full"
    elif rb.lstrip("-").isdigit():
        think = f"{_ctx_k(int(rb))} cap"   # a numeric thinking-token budget
    else:
        think = rb
    return (f"[b]▶ {escape(nm)}[/b]  {_ctx_k(lm.get('ctx'))} · {escape(q)}"
            + (f" · think {think}" if think else ""))


def _fmt(v, fmt: str = "{:.2f}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "—"


def _fmt_dur(s) -> str:
    """Compact run duration: 45s, 3m12s, 1h02m."""
    if not isinstance(s, (int, float)) or s <= 0:
        return "—"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


class NavTree(Tree):
    """Tree with file-explorer keys: ⏎ expands/collapses, space selects, ← collapses (or steps to
    parent), → expands. (Default Textual maps ⏎→select and space→toggle; we swap them.)"""
    BINDINGS = [
        Binding("enter", "toggle_node", "Expand/collapse"),
        Binding("space", "select_cursor", "Select"),
        Binding("left", "collapse_node", "Collapse"),
        Binding("right", "expand_node", "Expand"),
    ]

    def action_collapse_node(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.move_cursor(node.parent)     # already collapsed/leaf → step up, like a file explorer

    def action_expand_node(self) -> None:
        node = self.cursor_node
        if node is not None and node.allow_expand and not node.is_expanded:
            node.expand()


class ModelTree(NavTree):
    """The models picker tree. ⏎ is contextual: expand/collapse a family, download a quant that isn't
    downloaded yet, or run one that is. (→/← still expand/collapse; r always runs.)"""
    BINDINGS = [Binding("enter", "activate", "Expand / download / run")]

    def action_activate(self) -> None:
        node = self.cursor_node
        d = (node.data if node else None) or {}
        if d.get("kind") == "family":
            node.collapse() if node.is_expanded else node.expand()
        else:
            self.screen.action_enter()       # quant: run if local, else confirm download+run


class BoardTree(NavTree):
    """The leaderboard tree: model → quant run → per-challenge results. ⏎ (and →/←) drill in/out:
    expand a model to its quant runs, a quant run to the tests it ran; ⏎ on a test opens the
    challenge + the model's proposed solution side by side."""
    BINDINGS = [Binding("enter", "activate", "Expand / open")]

    def action_activate(self) -> None:
        node = self.cursor_node
        d = (node.data if node else None) or {}
        if d.get("kind") == "result":
            self.app.open_solution(d, self._quant_row(node))
        elif node is not None:
            node.collapse() if node.is_expanded else node.expand()

    @staticmethod
    def _quant_row(node) -> dict | None:
        """Walk up from a result leaf to its quant-run ancestor, whose row carries the run's model
        identity (family/quant/ctx) — used to label whose response this is."""
        p = getattr(node, "parent", None)
        while p is not None:
            if (p.data or {}).get("kind") == "quant":
                return p.data.get("row")
            p = getattr(p, "parent", None)
        return None


def _mem(vram, ram) -> str:
    """Memory a run used: 'VRAM/RAM' so a model too big for VRAM that spills to system RAM (and still
    runs at usable tok/s) reads sensibly. Falls back to whichever is known."""
    v = f"{vram:g}" if isinstance(vram, (int, float)) else None
    r = f"{ram:g}" if isinstance(ram, (int, float)) else None
    if v and r:
        return f"{v}/{r} GB"
    return f"{v or r} GB" if (v or r) else "?"


def _ctx_k(ctx) -> str:
    """Context length as K-tokens, e.g. 32768 -> '32K'."""
    if not isinstance(ctx, (int, float)) or ctx <= 0:
        return "—"
    return f"{ctx / 1024:g}K" if ctx >= 1024 else str(int(ctx))


def _think_label(v) -> str | None:
    """Human label for a reasoning override: 'on'->full, 'off'->off, int N->'4K cap', None->None."""
    if v == "on":
        return "full"
    if v == "off":
        return "off"
    if isinstance(v, int):
        return f"{_ctx_k(v)} cap"
    return None


def _model_says(name, quant=None, ctx=None, reasoning=None) -> str:
    """The `<model · quant · ctx> says:` identity line shown between the challenge and the model's
    response, in both the live run viewer and the solution explorer. Reasoning appended when known."""
    bits = [str(name or "model")]
    if quant and quant != "?":
        bits.append(str(quant))
    if ctx:
        bits.append(_ctx_k(ctx))
    if reasoning:
        bits.append(f"think {reasoning}")
    return f"[b]<{' · '.join(bits)}>[/] [dim]says:[/]"


# sensible context choices offered when launching a run; None = the model's configured default.
CTX_CHOICES = [None, 4096, 8192, 16384, 32768, 65536, 131072]


def _short_gpu(name: str | None) -> str:
    return (name or "").replace("NVIDIA GeForce ", "").replace("NVIDIA ", "").strip()


def _short_cpu(name: str | None) -> str:
    s = name or ""
    for junk in ("(R)", "(TM)", " CPU", " Processor"):
        s = s.replace(junk, "")
    s = re.sub(r"\s*\d+-Core", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _hw(run: dict) -> str:
    """Hardware a run used: 'GPU VRAM · CPU RAM' for the scoreboard. Parts with no name are omitted."""
    gpu, cpu = _short_gpu(run.get("gpu")), _short_cpu(run.get("cpu"))
    vram, ram = run.get("vram_gb"), run.get("ram_gb")
    parts = []
    if gpu:
        parts.append(f"{gpu} {vram:g}G" if isinstance(vram, (int, float)) else gpu)
    if cpu:
        parts.append(f"{cpu} {ram:g}G" if isinstance(ram, (int, float)) else cpu)
    return " · ".join(parts)


# Live-generation stream protocol — must match peakstone.engine.runner (GEN_MARK / GEN_NL).
GEN_MARK = "\x01"
GEN_NL = "\x02"
GEN_PHASE = "\x03"         # a line GEN_PHASE+"thinking"|"answering": the model's current channel
GEN_ATTEMPT = "\x04"       # a line GEN_ATTEMPT+"N": a self-repair retry began
_RUN_LOG_MAX = 8000        # bounded ring of streamed run lines (caps memory under a token flood)

# Render the runner's per-challenge progress markers as checkmarks in the live run log.
_PROGRESS_MARKS = [("  → solving", "  [dim]⟳[/]"), ("  ok ", "  [green]✓[/] "),
                   ("  !! ", "  [red]✗[/] "), ("  ERROR ", "  [red]✗ ERROR[/] "),
                   ("  SKIP ", "  [dim]· SKIP[/] ")]


def _pretty_progress(s: str) -> str:
    # Fully neutralize the runner/model text before we inject our own markup below: rich.markup.escape
    # only escapes *tag-shaped* brackets, which mismatched the parser and crashed mid-run on shapes
    # like `[^[]`. Escaping every `[` is parser-proof (Rich only treats `\` as special before a `[`,
    # so backslashes/regex/paths render unchanged, and none of the marks' search keys contain `[`).
    s = s.replace("[", r"\[")
    for a, b in _PROGRESS_MARKS:
        s = s.replace(a, b)
    return s


def _parse_result(s: str) -> tuple[str, str, str] | None:
    """Parse a runner per-challenge result line into (challenge_id, status_glyph, info) for the
    completed-tests table, or None if the line isn't a per-challenge result. The runner labels every
    such line `<model> | <challenge>  <outcome…>` (the same ' | ' heuristic the app uses to count
    coverage). '→ solving' lines are progress, not results, and are excluded."""
    if " | " not in s or "→ solving" in s:
        return None
    right = s.split("|", 1)[1].strip()          # "<challenge>  <outcome…>"
    parts = right.split(None, 1)
    if not parts:
        return None
    ch = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    if rest.startswith("ERROR") or rest.startswith("PLAN ERROR"):
        status = "[red]✗[/]"
    elif rest.startswith("SKIP"):
        status = "[dim]·[/]"
    else:
        m = re.search(r"final=([\d.]+)", rest)
        if m:
            f = float(m.group(1))
            status = "[green]✓[/]" if f >= 0.999 else ("[yellow]◐[/]" if f > 0 else "[red]✗[/]")
        elif rest.startswith("ok"):
            status = "[green]✓[/]"
        elif rest.startswith("!!"):
            status = "[red]✗[/]"
        else:
            status = "·"
    for pre in ("ok ", "!! "):                  # the glyph already conveys pass/fail; drop the marker
        if rest.startswith(pre):
            rest = rest[len(pre):].strip()
            break
    if "✂truncated" in rest:                     # cut off at the token budget (likely mid-thought)
        status = "[magenta]✂[/]"                 # distinct from a genuine ✗ — it's a budget signal
    return ch, status, rest


class HardwarePanel(Static):
    """Live GPU/CPU/RAM meters, refreshed every second."""

    def on_mount(self) -> None:
        self.set_interval(1.0, self._safe_refresh)
        self._safe_refresh()

    def _safe_refresh(self) -> None:
        # Another per-tick UI timer: a hiccup reading hardware (e.g. a flaky pgrep/nvidia-smi) must
        # not raise out of the callback and crash the app. Swallow and try again next second.
        try:
            self.refresh_stats()
        except Exception:  # noqa: BLE001
            pass

    def refresh_stats(self) -> None:
        s = hardware.snapshot()
        # every served model, right-pinned; the first sits on the primary GPU's line, the rest stack
        # under it on lines that are empty on the left (multiple models loaded on the same card).
        details = [_model_detail(lm) for lm in hardware.loaded_models() if lm.get("file")]
        # live run status rides right-aligned on the model's line, right after its name (not on a
        # separate line lower down). Concise: "🧠 thinking 48 tok/s" / "✍ answering 48 tok/s".
        status = self.app.run_status_inline()
        if details and status:
            details[0] = f"{details[0]}    {status}"

        def _gpu_row(left: str, right: str):
            """One GPU line: meter on the left, loaded-model detail pinned to the right corner."""
            row = Table.grid(expand=True, padding=(0, 1))
            row.add_column(justify="left", ratio=1, no_wrap=True)
            row.add_column(justify="right", no_wrap=True)
            row.add_row(left, right)
            return row

        rows = []
        if s.gpus:
            for i, g in enumerate(s.gpus):
                rows.append(_gpu_row(
                    f"{_meter('VRAM', g.mem_used_mib, g.mem_total_mib)}  "
                    f"[b]GPU{g.index}[/b] {g.name}  util {g.util_pct}%",
                    details[0] if (i == 0 and details) else ""))
                if i == 0:                       # extra models on this card: blank left, pinned right
                    for d in details[1:]:
                        rows.append(_gpu_row("", d))
        else:
            rows.append(_gpu_row("[yellow]No GPU detected — CPU only[/yellow]",
                                 details[0] if details else ""))
            for d in details[1:]:
                rows.append(_gpu_row("", d))
        names = s.cpu_names or ["CPU"]            # " RAM" lines up under "VRAM"; CPU0 under GPU0
        rows.append(Text.from_markup(
            f"{_meter(' RAM', s.ram_used_mib, s.ram_total_mib)}  "
            f"[b]CPU0[/b] {escape(names[0])}  {s.cpu_pct:.1f}% ({s.cores} cores)"))
        for i, nm in enumerate(names[1:], start=1):   # dual-socket boxes: CPU1, CPU2… aligned under CPU0
            rows.append(Text.from_markup(f"{' ' * 44}  [b]CPU{i}[/b] {escape(nm)}"))
        job = self.app.job_status()
        if job:
            t = Text.from_markup(job)
            t.justify = "right"                          # the run/queue line sits on the right
            rows.append(t)
        self.border_title = time.strftime("%a %H:%M:%S")   # the clock lives with the live hardware info
        self.update(Group(*rows))


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
                  free_procs=None, ctx=None, reasoning=None, budget=None, download_only=False):
        """Enqueue a benchmark on the DAEMON's run queue (the single source of truth) and return its
        job id (None if the daemon is unreachable). The daemon serializes runs on the GPU and
        auto-downloads a missing model first; this app just mirrors whatever it's running. free_procs
        is unused now that the daemon owns serving (it swaps models itself)."""
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
        # The daemon already auto-submits, but it runs on this same host, so read its bundle off disk
        # to enable manual re-submit ('s' in the viewer) and keep the result line's submit state.
        bundle = None
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


class ReproduceScreen(ModalScreen):
    """Reproduce a model on local hardware and compare your tok/s to the published number."""
    CSS = """
    ReproduceScreen { layout: vertical; background: $surface; }  /* opaque: no base board bleeding through */
    ReproduceScreen HardwarePanel { margin: 0; }                 /* flush to the top/sides (full-bleed) */
    #repro { width: 100%; height: 1fr; border: thick $accent; background: $surface; padding: 0 1; }
    #repro-stat { height: auto; padding-bottom: 1; }
    /* dim gray = inactive (recedes); bright blue = the active scroll pane (pops forward) */
    #repro-completed { height: 1fr; border: round dimgray; }
    #repro-completed:focus { border: round dodgerblue; }
    #repro-says { height: auto; padding: 0 1; color: $accent; }  /* identity line above the output */
    #repro-gen-wrap { height: 45%; border: round dimgray; margin-top: 1; }
    #repro-gen-wrap:focus { border: round dodgerblue; }
    #repro-gen { width: 1fr; }
    #repro-result { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("s", "submit", "Submit"),
                ("tab", "toggle_pane", "Switch pane")]
    LIVE_KEY = "__live__"

    def __init__(self):
        super().__init__()
        self._result: reproduce.ReproduceResult | None = None
        self._gen_buf = ""       # accumulated live model output for the current challenge (render-capped)
        self._gen_ch = ""        # the challenge currently being solved (from the runner's progress)
        self._gen_phase: str | None = None     # "thinking" | "answering" — the model's live channel
        self._solutions: dict[str, str] = {}   # challenge id -> its captured model output (for review)
        self._completed: set[str] = set()       # challenge ids already added as a completed-table row
        self._viewing: str | None = None        # None = follow live; else a completed challenge under review
        # coverage/done/total/elapsed are owned by the app (single source of truth); the view reads them.

    def compose(self) -> ComposeResult:
        # top status = live hardware (with the clock); then the run-context title bar; bottom = Footer
        # (key shortcuts). No generic app header — the bar under the hardware relates to this run.
        yield HardwarePanel()
        with Vertical(id="repro"):
            yield Static("", id="repro-title")
            yield Static("", id="repro-stat")
            yield DataTable(id="repro-completed", cursor_type="row", zebra_stripes=True)
            yield Static("", id="repro-says")     # "<model · quant · ctx> says:" — between the panes
            with VerticalScroll(id="repro-gen-wrap"):
                yield Static("[dim]model output appears here as it solves each task[/]", id="repro-gen")
            yield Static("running…  ·  ↑↓ pick a finished test to review", id="repro-result")
        yield Footer()

    def on_mount(self) -> None:
        self.app._viewer = self                 # the active run streams into this view
        tbl = self.query_one("#repro-completed", DataTable)
        self._col_status = tbl.add_column(" ", width=2)
        self._col_test = tbl.add_column("test", width=30)
        self._col_info = tbl.add_column("result")
        self.query_one("#repro-gen-wrap", VerticalScroll).can_focus = True   # scrollable + Tab-focusable
        self.reset_view()
        for line in list(self.app._run_log):    # backfill what already streamed (re-opened mid-run)
            self._on_line(line)
        self._seen_n = self.app._run_log_n      # then the timer renders only lines emitted after this
        if self.app._run_result is not None:
            self.show_result(self.app._run_result)
        self.query_one("#repro-gen-wrap", VerticalScroll).focus()   # scroll the live output by default
        self._log_timer = self.set_interval(0.1, self._drain_log)   # pull streamed lines off-thread

    def on_unmount(self) -> None:
        if getattr(self, "_log_timer", None) is not None:
            self._log_timer.stop()
        if self.app._viewer is self:            # leaving the view doesn't stop the run
            self.app._viewer = None

    def _drain_log(self) -> None:
        """Render run lines buffered by the reader thread. Runs on the UI thread (so it can touch
        widgets); the reader thread only appends — never blocks. Coalesces under a flood: if we fell
        behind past the bounded ring, skip to the most recent retained lines."""
        n = self.app._run_log_n
        new = n - getattr(self, "_seen_n", 0)
        if new <= 0:
            return
        buf = list(self.app._run_log)           # snapshot (deque isn't sliceable)
        lines = buf[-new:] if new <= len(buf) else buf
        self._seen_n = n
        for line in lines[-1500:]:              # cap per tick to keep the UI responsive under a flood
            try:
                self._on_line(line)
            except Exception:                  # noqa: BLE001
                # Last-resort guard: a single un-renderable line must NEVER propagate out of this UI
                # timer, because an unhandled exception here tears down the whole TUI (and the live
                # view of a long run with it). The run itself is a detached subprocess and survives a
                # dead viewer regardless, but we don't even want to lose the view. Skip the bad line.
                pass

    def reset_view(self) -> None:
        """(Re)point the view at the app's current run — clears widgets and counters for a new run."""
        spec = self.app._run_spec or {}
        model, level = spec.get("name", "—"), spec.get("level")
        ids = spec.get("challenge_ids") or REPRODUCE_IDS
        self._result = None
        self._seen_n = 0                         # new run → render its streamed lines from the start
        self._gen_buf, self._gen_ch, self._gen_phase = "", "", None
        self._solutions, self._completed, self._viewing = {}, set(), None
        scope = "download" if spec.get("download_only") else (f"level {level}" if level else f"{len(ids)} challenges")
        ctx = f"  ·  ctx {_ctx_k(spec.get('ctx'))}" if spec.get("ctx") else ""
        budget = f"  ·  budget {_ctx_k(spec.get('budget'))}" if spec.get("budget") else ""
        _nq = self.app.queued_count()
        queued = f"  ·  {_nq} queued" if _nq else ""
        self.query_one("#repro-title", Static).update(
            f"[b]Run[/b] {model}  ·  {scope}{ctx}{budget}  ·  published "
            f"{_fmt(spec.get('published_tps'), '{:.0f}')} tok/s{queued}")
        entry = models.load_registry().get(model)   # the model identity line shown above the output
        says = _model_says(model, entry.quant if entry else None, spec.get("ctx"),
                           _think_label(spec.get("reasoning")))
        self.query_one("#repro-says", Static).update("" if spec.get("download_only") else says)
        tbl = self.query_one("#repro-completed", DataTable)
        tbl.clear()                              # keep columns, drop rows
        tbl.add_row(Text.from_markup("[cyan]●[/]"), Text("(running)"), Text(""),
                    key=self.LIVE_KEY)           # the live/current row — kept pinned to the BOTTOM as
                                                 # tests finish (see _add_completed)
        self.query_one("#repro-gen", Static).update("[dim]model output appears here as it solves each task[/]")
        self.query_one("#repro-result", Static).update(
            "running…  ·  ↑↓ pick a finished test to review")

    def _on_line(self, s: str) -> None:
        """Route a streamed line: generation deltas (control-prefixed) stream into the output panel and
        accumulate per-challenge (for later review); result lines become rows in the completed-tests
        table. Coverage/sol-s come from the app's counters (single source of truth)."""
        if s.startswith(GEN_MARK):
            delta = s[len(GEN_MARK):].replace(GEN_NL, "\n")
            self._gen_buf = (self._gen_buf + delta)[-8000:]            # render-capped (live perf)
            if self._gen_ch:                                          # keep a fuller copy for review
                self._solutions[self._gen_ch] = (self._solutions.get(self._gen_ch, "") + delta)[-24000:]
            self._render_gen()
            return
        if s.startswith(GEN_PHASE):
            self._gen_phase = s[len(GEN_PHASE):]   # "thinking" | "answering" — shown in the panel header
            # mark the boundary in the retained copy so the review reads as sectioned thinking / answer
            hdr = {"thinking": "\n── thinking ──\n", "answering": "\n── answer ──\n"}.get(self._gen_phase)
            if hdr and self._gen_ch:
                self._solutions[self._gen_ch] = (self._solutions.get(self._gen_ch, "") + hdr)[-24000:]
            self._render_gen()
            return
        if s.startswith(GEN_ATTEMPT):
            n = s[len(GEN_ATTEMPT):]               # a self-repair retry began → section it in the review
            if self._gen_ch:
                mark = f"\n━━━━━ attempt {n} ━━━━━\n"
                self._solutions[self._gen_ch] = (self._solutions.get(self._gen_ch, "") + mark)[-24000:]
            self._gen_phase = None
            self._render_gen()
            return
        if "→ solving" in s:
            # the "solving" line shows live in the gen panel header; it isn't logged (each test is one
            # row — its result — not a "solving" line followed by its ✓/✗).
            self._gen_ch = s.split("→ solving")[0].split("|")[-1].strip()
            self._gen_buf, self._gen_phase = "", None
            self._solutions.setdefault(self._gen_ch, "")
            self._update_live_row()
            self._render_gen()
            self._update_stat()
            return
        parsed = _parse_result(s)               # a per-challenge result/skip/error line?
        if parsed:
            self._add_completed(*parsed)
        self._update_stat()

    def _update_live_row(self) -> None:
        tbl = self.query_one("#repro-completed", DataTable)
        try:
            tbl.update_cell(self.LIVE_KEY, self._col_test, Text(self._gen_ch or "(running)"))
        except Exception:  # noqa: BLE001 — row gone (cleared); next reset re-adds it
            pass

    def _add_completed(self, ch: str, status: str, info: str) -> None:
        if ch in self._completed:               # one row per challenge (retries print a single line)
            return
        self._completed.add(ch)
        tbl = self.query_one("#repro-completed", DataTable)
        follow = tbl.scroll_y >= tbl.max_scroll_y - 2   # stay pinned to the bottom only if already there
        # Keep the live/current row at the BOTTOM: drop it, append the finished test (so completed tests
        # accumulate top-to-bottom in order), then re-add the live row last. status carries intentional
        # color markup; info is raw runner text that may contain literal brackets (e.g. "[on try 1/2]"),
        # so render it as a Text — never parsed.
        try:
            tbl.remove_row(self.LIVE_KEY)
        except Exception:  # noqa: BLE001 — live row absent (cleared); the add below re-establishes it
            pass
        tbl.add_row(Text.from_markup(status), Text(ch), Text(info), key=ch)
        tbl.add_row(Text.from_markup("[cyan]●[/]"), Text("(running)"), Text(""), key=self.LIVE_KEY)
        # Removing the cursor's row shifts the cursor and would fire a spurious highlight (hijacking the
        # review pane). Restore it to match what the user is looking at: the live row when following.
        target = self.LIVE_KEY if self._viewing is None else self._viewing
        try:
            tbl.move_cursor(row=tbl.get_row_index(target))
        except Exception:  # noqa: BLE001
            pass
        if follow:
            tbl.scroll_end(animate=False)

    def _update_stat(self) -> None:
        p = self.app.run_progress()             # app owns the counters; the view just renders them
        if p["phase"] == "download" and p["dl_total"]:
            self.query_one("#repro-stat", Static).update(
                f"[b]downloading[/]  {_bar(p['dl_done'], p['dl_total'])}  "
                f"{p['dl_done'] / 1e9:.1f}/{p['dl_total'] / 1e9:.1f} GB")
            return
        elapsed = (time.monotonic() - p["t0"]) if p["t0"] else 0.0
        rate = (p["done"] / elapsed) if elapsed > 0 else 0.0
        total = p["total"] or "?"
        done = min(p["done"], p["total"]) if p["total"] else p["done"]
        corpus = self.app.corpus_total()
        suite = f"   ·   {p['total']}/{corpus} of suite" if (p["total"] and corpus) else ""
        self.query_one("#repro-stat", Static).update(
            f"[b]coverage[/] {done}/{total}{suite}   ·   [b]{rate:.2f}[/] sol/s   ·   "
            f"elapsed {int(elapsed // 60)}:{int(elapsed % 60):02d}")

    def _render_gen(self) -> None:
        if self._viewing is not None:           # user is reviewing a completed test — don't clobber it
            return
        phase = {"thinking": "  ·  [magenta]🧠 thinking[/]",
                 "answering": "  ·  [green]✍ answering[/]"}.get(self._gen_phase, "")
        head = Text.from_markup(
            (f"[b]solving[/] {escape(self._gen_ch)}{phase}" if self._gen_ch else "[dim]model output[/]"))
        # the model's live output (esp. a reasoner's chain-of-thought) is full of [ ] / backticks /
        # code that Rich's markup parser chokes on. escape() doesn't catch every bracket shape (it
        # crashed mid-run on e.g. `[^[]`), so render the body as a Text — a renderable Static never
        # markup-parses — making a MarkupError structurally impossible.
        head.append("\n")
        head.append_text(Text(self._gen_buf))
        self._set_output(head, follow=True)

    def _render_review(self, ch: str) -> None:
        """Show a completed test's captured solution in the output panel (static, scrolled to the top)."""
        body = self._solutions.get(ch) or "(no captured output for this test)"
        head = Text.from_markup(f"[b]{escape(ch)}[/] — proposed solution  [dim](completed)[/]")
        head.append("\n")
        head.append_text(Text(body))
        self._set_output(head, follow=False)

    def _set_output(self, renderable, *, follow: bool) -> None:
        """Update the output panel. follow=True keeps the view pinned to the bottom ONLY if it was
        already there — so once the user scrolls up to read, live generation never yanks them back
        down. follow=False (review) jumps to the top so the solution reads from the start."""
        wrap = self.query_one("#repro-gen-wrap", VerticalScroll)
        at_bottom = wrap.scroll_y >= wrap.max_scroll_y - 2
        self.query_one("#repro-gen", Static).update(renderable)
        if not follow:
            wrap.scroll_home(animate=False)
        elif at_bottom:
            wrap.scroll_end(animate=False)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        try:
            key = event.row_key.value if event.row_key is not None else None
            if key in (None, self.LIVE_KEY):     # back on the live row → resume following generation
                self._viewing = None
                self._render_gen()
            else:                                # a completed test → show its captured solution
                self._viewing = key
                self._render_review(key)
        except Exception:  # noqa: BLE001 — selecting a row must never crash the viewer mid-run
            pass

    def action_toggle_pane(self) -> None:
        """Tab: switch focus between the completed-tests table (↑↓ picks a test) and the output panel
        (↑↓ scrolls the solution at your own pace)."""
        tbl = self.query_one("#repro-completed", DataTable)
        wrap = self.query_one("#repro-gen-wrap", VerticalScroll)
        (tbl if self.focused is wrap else wrap).focus()

    def show_result(self, res: "reproduce.ReproduceResult") -> None:
        self._result = res
        out = self.query_one("#repro-result", Static)
        if res.download:
            out.update(f"[green b]downloaded ✓[/] — {res.note}" if res.ok
                       else f"[red b]download failed[/] — {res.note}")
            return
        if res.ok:
            ratio = f"  ([b]{res.tps_ratio}×[/b] published)" if res.tps_ratio else ""
            if not res.bundle:
                submit_hint = ""
            elif self.app._run_submitted:                       # auto-submitted already
                submit_hint = "  ·  [dim]submitted ✓[/]"
            else:
                submit_hint = "  ·  press [b]s[/] to submit"
            out.update(f"[green b]done[/]  ·  your [b]{_fmt(res.your_tps, '{:.0f}')}[/] tok/s vs published "
                       f"{_fmt(res.published_tps, '{:.0f}')}{ratio}  ·  code {_fmt(res.code_score)} "
                       f"({res.passed}/{res.total}){submit_hint}")
        else:
            out.update(f"[red b]failed[/] — {res.note}")

    def action_submit(self) -> None:
        if not (self._result and self._result.ok and self._result.bundle):
            self.notify("nothing to submit yet")
            return
        self.submit_bundle()

    @work(thread=True, exclusive=True)
    def submit_bundle(self) -> None:
        try:
            status, detail = client.submit_bundle(self.app.base_url, self._result.bundle)
        except client.APIError as e:
            self.app.call_from_thread(self.app.notify, f"submit failed: {e}", severity="error")
            return
        msg = {201: "submitted ✓", 409: "already submitted", 400: "rejected"}.get(status, f"status {status}")
        self.app.call_from_thread(self.app.notify, f"{msg}")


def _solution_body(r: dict) -> str:
    """Bottom-pane text for a test result: the model's thinking, its solution, then the execution
    output and the test's reaction (pass/fail). For iterative runs (agentic/repo-patch) raw_output is
    the full turn-by-turn transcript, so each attempt and its result already appear in order."""
    tr = r.get("transcript") or {}
    parts = []
    attempts = tr.get("attempts")
    if attempts:   # a self-repair loop ran → the whole story: each try's thinking, answer, and the
        n = len(attempts)   # error fed back before the next, in order
        for i, a in enumerate(attempts, 1):
            parts.append(f"━━━━━ attempt {i}/{n} ━━━━━")
            if a.get("reasoning"):
                parts.append("── thinking ──\n" + a["reasoning"])
            parts.append("── answer ──\n" + (a.get("answer") or "(no answer)"))
            parts.append(f"── tests ──\n{a.get('passed', 0)}/{a.get('total', 0)} passed")
            if a.get("test_error"):
                parts.append("── error fed back to the model ──\n" + a["test_error"])
    else:
        if tr.get("reasoning"):
            parts.append("── thinking ──\n" + tr["reasoning"])
        if tr.get("plan"):
            parts.append("── plan ──\n" + tr["plan"])
        parts.append("── proposed solution ──\n" + (tr.get("raw_output") or "(no solution recorded for this run)"))
    if tr.get("stdout"):
        parts.append("── output ──\n" + tr["stdout"])
    if tr.get("stderr"):
        parts.append("── errors ──\n" + tr["stderr"])
    final = r.get("final")
    pt = f"  {r['passed']}/{r['total']} tests" if r.get("total") else ""
    if tr.get("error") == "repetition-loop":
        verdict = "REPETITION LOOP (generation aborted)"
    else:
        verdict = "PASS" if (final or 0) >= 0.999 else ("FAIL" if final == 0 else "PARTIAL")
    parts.append(f"── result ──\n{verdict}   score {final if final is not None else '—'}{pt}")
    return "\n\n".join(parts)


class SolutionScreen(ModalScreen):
    """A test's challenge spec (top) and the model's solution + result (bottom), split like the runner.
    The bottom pane shows the proposed solution, the execution output, and the test's reaction; for
    iterative runs the attempts and their results appear in order within the transcript."""
    CSS = """
    SolutionScreen { layout: vertical; background: $surface; }   /* opaque: no base board bleeding through */
    SolutionScreen HardwarePanel { margin: 0; }                  /* flush to the top/sides (full-bleed) */
    #sol { width: 100%; height: 1fr; border: thick $accent; background: $surface; padding: 0 1; }
    /* dim gray = inactive (recedes); bright blue = the active scroll pane (pops forward) */
    #sol-spec-wrap { height: 1fr; border: round dimgray; }
    #sol-spec-wrap:focus { border: round dodgerblue; }
    #sol-out-wrap { height: 1fr; border: round dimgray; margin-top: 1; }
    #sol-out-wrap:focus { border: round dodgerblue; }
    #sol-says { height: auto; padding: 0 1; color: $accent; }   /* identity line between the panes */
    #sol-spec, #sol-out { width: 1fr; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("tab", "toggle_pane", "Switch pane")]

    def __init__(self, challenge_id: str, spec: str | None, base_url: str, bundle_hash: str | None,
                 model_label: str | None = None):
        super().__init__()
        self.challenge_id = challenge_id
        self.spec = spec
        self.base_url = base_url
        self.bundle_hash = bundle_hash
        self.model_label = model_label        # "<model · quant · ctx> says:" — whose response this is

    def compose(self) -> ComposeResult:
        # top status = live hardware (with the clock); then this challenge's context bar; bottom = Footer
        yield HardwarePanel()
        with Vertical(id="sol"):
            yield Static(f"[b]{self.challenge_id}[/]  ·  system prompt + challenge (top) · thinking + solution (bottom)  ·  ↑↓ scroll")
            with VerticalScroll(id="sol-spec-wrap"):
                # markup off: specs/solutions contain [ ] that Rich would try to parse
                yield Static(self.spec or "(challenge spec not in the local corpus)", id="sol-spec", markup=False)
            # the identity line sits BETWEEN the two panes, in both this view and the live run viewer
            yield Static(self.model_label or "", id="sol-says")
            with VerticalScroll(id="sol-out-wrap"):
                yield Static("loading…", id="sol-out", markup=False)
        yield Footer()                          # … and on the bottom (matches the run viewer)

    def on_mount(self) -> None:
        self.query_one("#sol-out-wrap", VerticalScroll).focus()   # active pane (highlighted) by default
        self.load_solution()                 # fetch the (potentially large) transcript on demand

    def action_toggle_pane(self) -> None:
        """Tab: switch the active scroll pane between the challenge spec and the solution."""
        spec = self.query_one("#sol-spec-wrap", VerticalScroll)
        out = self.query_one("#sol-out-wrap", VerticalScroll)
        (spec if self.focused is out else out).focus()

    @work(thread=True, exclusive=True)
    def load_solution(self) -> None:
        spec_text = None
        if not self.bundle_hash:
            body = "(no run reference — solution unavailable)"
        else:
            try:
                r = client.get_run_challenge(self.base_url, self.bundle_hash, self.challenge_id)
                body = _solution_body(r)
                sysp = (r.get("transcript") or {}).get("system_prompt")
                if sysp:   # show the exact instructions the model was given, before the challenge
                    base = self.spec or "(challenge spec not in the local corpus)"
                    spec_text = f"── system prompt ──\n{sysp}\n\n── challenge ──\n{base}"
            except client.APIError as e:
                body = f"(could not load solution: {e})"
        if spec_text is not None:
            self.app.call_from_thread(self.query_one("#sol-spec", Static).update, spec_text)
        self.app.call_from_thread(self.query_one("#sol-out", Static).update, body)


class ConfirmScreen(ModalScreen):
    """Generic yes/no confirmation; runs on_yes when confirmed."""
    CSS = """
    ConfirmScreen { align: center middle; }
    #confirm { width: 64; height: auto; border: thick $accent; background: $surface; padding: 1; }
    """
    BINDINGS = [("escape", "dismiss", "No"), ("n", "dismiss", "No"),
                ("y", "yes", "Yes"), ("enter", "yes", "Yes")]

    def __init__(self, message: str, on_yes):
        super().__init__()
        self.message = message
        self._on_yes = on_yes

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Static(f"{self.message}\n\n[b]y[/]/⏎ yes   ·   [b]Esc[/] no")

    def action_yes(self) -> None:
        self.dismiss()
        self._on_yes()


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


class AddModelScreen(ModalScreen):
    CSS = """
    AddModelScreen { align: center middle; }
    #addmodel { width: 76; height: auto; border: thick $accent; background: $surface; padding: 1; }
    #addmodel Input { margin-bottom: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="addmodel"):
            yield Static("[b]Add a model[/b]  (registers it in serve/models.toml)")
            yield Input(placeholder="name  e.g. qwen3-coder", id="m-name")
            yield Input(placeholder="HF repo  e.g. unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", id="m-repo")
            yield Input(placeholder="GGUF filename  e.g. Qwen3-Coder-...-Q4_K_XL.gguf", id="m-file")
            yield Static("", id="addmodel-err")
            yield Button("Add", id="m-add", variant="primary")

    def on_button_pressed(self, _: Button.Pressed) -> None:
        try:
            models.add_model(self.query_one("#m-name", Input).value.strip(),
                             self.query_one("#m-repo", Input).value.strip(),
                             self.query_one("#m-file", Input).value.strip() or None)
            self.dismiss(True)
        except ValueError as e:
            self.query_one("#addmodel-err", Static).update(f"[red]{e}[/]")


class PreflightScreen(ModalScreen):
    """Shown before serving when free accelerator memory looks too small for the model. Offers to free
    our own llama-server processes (Linux: GPU VRAM; macOS: unified RAM) or run anyway."""
    CSS = """
    PreflightScreen { align: center middle; }
    #preflight { width: 76; height: auto; border: thick $warning; background: $surface; padding: 1; }
    """

    def __init__(self, model_name: str, pf: "preflight.Preflight", on_proceed):
        super().__init__()
        self.model_name = model_name
        self.pf = pf
        self._on_proceed = on_proceed   # on_proceed(free_first: bool)

    def compose(self) -> ComposeResult:
        pf = self.pf
        lines = ["[b yellow]Memory looks tight[/]",
                 f"{self.model_name} needs ~[b]{pf.need_gb}[/] GB · [b]{pf.free_gb}[/] GB free"]
        if pf.freeable:
            lines.append(f"\n{len(pf.freeable)} llama-server process(es) holding {pf.freeable_gb} GB:")
            lines += [f"  · pid {p.pid} ({p.name})  {p.used_gb} GB" for p in pf.freeable]
            verdict = "→ freeing them should make room." if pf.fits_after_free \
                else "→ may still not fit even after freeing."
            lines.append(verdict)
            lines.append("\n[b]f[/] free & run   ·   [b]r[/] run anyway   ·   [b]Esc[/] cancel")
        else:
            lines.append("\nNo llama-servers of ours to free — close other GPU apps, or:")
            lines.append("[b]r[/] run anyway   ·   [b]Esc[/] cancel")
        with Vertical(id="preflight"):
            yield Static("\n".join(lines))

    BINDINGS = [("escape", "cancel", "Cancel"), ("f", "free_run", "Free & run"),
                ("r", "run_anyway", "Run anyway")]

    def action_free_run(self) -> None:
        if self.pf.freeable:
            self.dismiss()
            self._on_proceed(True)

    def action_run_anyway(self) -> None:
        self.dismiss()
        self._on_proceed(False)

    def action_cancel(self) -> None:
        self.dismiss()


def run_with_preflight(screen, name: str, *, challenge_ids=None, level=None, published_tps=None) -> None:
    """Queue a reproduce run, first checking free accelerator memory. If a model won't fit, prompt to
    free our llama-servers (or run anyway) before queuing; a fresh run opens the live view, a run
    started while one is active is queued behind it."""
    app = screen.app
    entry = models.load_registry().get(name)
    pf = preflight.check(entry) if entry else None

    def launch(free_first: bool) -> None:
        procs = pf.freeable if (free_first and pf) else None
        started = app.start_run(name, published_tps=published_tps, challenge_ids=challenge_ids,
                                level=level, free_procs=procs, ctx=app.ctx_for(name),
                                reasoning=app.reasoning_for(name), budget=app.budget_for(name))
        if started:
            app.push_screen(ReproduceScreen())

    # The preflight VRAM check only matters when the run starts NOW. If a run is already active this
    # one is QUEUED, and the active model stops (freeing its VRAM) before it starts — so don't warn.
    if pf and not pf.fits_now and not app.run_active:
        app.push_screen(PreflightScreen(name, pf, on_proceed=launch))
    else:
        launch(False)


class CtxScreen(ModalScreen):
    """Pick the served context window for the next run. Each option is annotated with VRAM fit
    (weights + KV-cache vs the card) and how many selected long-context challenges it would skip.
    Options above the model's native ctx are dropped — llama-server can't serve beyond it."""
    CSS = """
    CtxScreen { align: center middle; }
    #ctx { width: 64; height: auto; max-height: 90%; border: thick $accent; background: $surface; padding: 1; }
    #ctx-tbl { height: auto; }
    #ctx-note { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("enter", "choose", "Select")]

    def __init__(self, entry, key, current):
        super().__init__()
        self.entry = entry            # the selected model's registry entry (None if unknown)
        self.key = key                # ctx_overrides key: the model name, or "" for the global default
        self.current = current        # the override currently set for this key
        self._rows: list = []         # row index -> ctx value (None = default/native)

    def compose(self) -> ComposeResult:
        native = getattr(self.entry, "ctx", None) if self.entry else None
        name = getattr(self.entry, "name", None) if self.entry else None
        head = (f"[b]Context[/b] for {name}" if name else "[b]Context[/b] (default for all models)") \
            + (f"  ·  native {_ctx_k(native)}" if native else "")
        with Vertical(id="ctx"):
            yield Static(head + "  ·  ⏎ select · Esc cancel")
            yield DataTable(id="ctx-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("", id="ctx-note")

    def on_mount(self) -> None:
        t = self.query_one("#ctx-tbl", DataTable)
        t.add_columns(" ", "Context", "VRAM", "Long-ctx")
        native = getattr(self.entry, "ctx", None) if self.entry else None
        total = hardware.snapshot().max_vram_gb or 24.0
        ids = set(self.app.effective_ids())
        lc = [c for c in self.app.corpus() if c.id in ids and c.min_ctx]   # selected long-ctx challenges
        choices = [None] + [c for c in CTX_CHOICES if c and (native is None or c <= native)]
        self._rows = choices
        cur = 0
        for i, ctx in enumerate(choices):
            eff = ctx or native or 32768          # "default" serves at the native window
            if ctx == self.current:
                cur = i
            label = (f"default ({_ctx_k(native)})" if (ctx is None and native)
                     else "default" if ctx is None else _ctx_k(ctx))
            need = preflight.vram_needed_gb(self.entry, eff) if self.entry else None
            if need is None:
                fit = "—"
            elif need <= 0.9 * total:
                fit = f"[green]✓[/] {need:.0f}G"
            elif need <= total:
                fit = f"[yellow]⚠[/] {need:.0f}G"
            else:
                fit = f"[red]✗[/] {need:.0f}G"
            nskip = sum(1 for c in lc if c.min_ctx > eff)
            skip = f"[yellow]skips {nskip}[/]" if nskip else ("[green]all[/]" if lc else "—")
            t.add_row(">" if ctx == self.current else " ", label, fit, skip)
        t.move_cursor(row=cur)
        note = f"VRAM ≈ weights + KV-cache vs {total:.0f}G card (rough)."
        if lc:
            note += f"  {len(lc)} long-context challenge(s) in this run."
        self.query_one("#ctx-note", Static).update(note)

    def on_data_table_row_selected(self, _event) -> None:
        self.action_choose()          # ⏎ on a row: the DataTable consumes enter, so route it here

    def action_choose(self) -> None:
        t = self.query_one("#ctx-tbl", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self._rows):
            return
        self.app.ctx_overrides[self.key] = self._rows[t.cursor_row]   # per model ("" = global default)
        self.dismiss()


class ReasoningScreen(ModalScreen):
    """Pick the reasoning (chain-of-thought) budget for the next run — a run condition like context.
    'off' disables thinking; 'full' lets it think freely; a numeric cap (e.g. 4k/8k) limits thinking
    to that many tokens then forces the answer (guarantees answer room — trace 'accuracy vs thinking
    budget'); 'default' keeps the model's configured budget. Numeric caps need model support."""
    CSS = """
    ReasoningScreen { align: center middle; }
    #rsn { width: 70; height: auto; border: thick $accent; background: $surface; padding: 1; }
    #rsn-tbl { height: auto; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("enter", "choose", "Select")]
    OPTIONS = [(None, "default", "use the model's configured reasoning budget"),
               ("on", "full", "think freely  (--reasoning-budget -1)"),
               (8192, "8k cap", "think up to 8192 tokens, then force the answer"),
               (4096, "4k cap", "think up to 4096 tokens, then force the answer"),
               (2048, "2k cap", "think up to 2048 tokens, then force the answer"),
               ("off", "off", "no thinking  (--reasoning-budget 0) — faster, often less accurate")]

    def __init__(self, entry, key, current):
        super().__init__()
        self.entry = entry            # the selected model's registry entry (None if unknown)
        self.key = key                # reasoning_overrides key: the model name, or "" for the default
        self.current = current        # the override currently set for this key

    def compose(self) -> ComposeResult:
        name = getattr(self.entry, "name", None) if self.entry else None
        head = (f"[b]Reasoning[/b] for {name}" if name else "[b]Reasoning[/b] (default for all models)")
        with Vertical(id="rsn"):
            yield Static(head + "  ·  ⏎ select · Esc cancel")
            yield DataTable(id="rsn-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("Only reasoning models think; for others this is a no-op.", id="rsn-note")

    def on_mount(self) -> None:
        t = self.query_one("#rsn-tbl", DataTable)
        t.add_columns(" ", "Mode", "Effect")
        cur = 0
        for i, (val, label, desc) in enumerate(self.OPTIONS):
            if val == self.current:
                cur = i
            t.add_row(">" if val == self.current else " ", label, desc)
        t.move_cursor(row=cur)

    def on_data_table_row_selected(self, _event) -> None:
        self.action_choose()

    def action_choose(self) -> None:
        t = self.query_one("#rsn-tbl", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self.OPTIONS):
            return
        self.app.reasoning_overrides[self.key] = self.OPTIONS[t.cursor_row][0]
        self.dismiss()


class BudgetScreen(ModalScreen):
    """Pick the generation token budget (max_tokens) for the next run — a run condition like context.
    A larger budget gives reasoning models room to finish (fewer truncated-mid-thought failures); a
    smaller one measures efficiency-at-task under a tighter cost. Recorded in the bundle so runs at
    different budgets stay distinguishable. Effective use is capped by the served context window."""
    CSS = """
    BudgetScreen { align: center middle; }
    #bdg { width: 72; height: auto; border: thick $accent; background: $surface; padding: 1; }
    #bdg-tbl { height: auto; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("enter", "choose", "Select")]
    OPTIONS = [(None, "default (16k)", "engine default — generous, avoids mid-thought truncation"),
               (8192, "8k", "constrained — measures efficiency-at-task under a tighter budget"),
               (24576, "24k", "extra room for heavy/inline reasoners"),
               (32768, "32k", "maximum headroom (slowest, most tokens spent)")]

    def __init__(self, entry, key, current):
        super().__init__()
        self.entry = entry            # the selected model's registry entry (None if unknown)
        self.key = key                # budget_overrides key: the model name, or "" for the default
        self.current = current        # the override currently set for this key

    def compose(self) -> ComposeResult:
        name = getattr(self.entry, "name", None) if self.entry else None
        head = (f"[b]Budget[/b] for {name}" if name else "[b]Budget[/b] (default for all models)")
        with Vertical(id="bdg"):
            yield Static(head + "  ·  ⏎ select · Esc cancel")
            yield DataTable(id="bdg-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("Generation token budget (max_tokens); effective use is capped by the served ctx.",
                         id="bdg-note")

    def on_mount(self) -> None:
        t = self.query_one("#bdg-tbl", DataTable)
        t.add_columns(" ", "Budget", "Effect")
        cur = 0
        for i, (val, label, desc) in enumerate(self.OPTIONS):
            if val == self.current:
                cur = i
            t.add_row(">" if val == self.current else " ", label, desc)
        t.move_cursor(row=cur)

    def on_data_table_row_selected(self, _event) -> None:
        self.action_choose()

    def action_choose(self) -> None:
        t = self.query_one("#bdg-tbl", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self.OPTIONS):
            return
        self.app.budget_overrides[self.key] = self.OPTIONS[t.cursor_row][0]
        self.dismiss()


class ModelsScreen(ModalScreen):
    """Pick a model to run the selected challenges on. Models are grouped as family → quant: the
    registry (serve/models.toml) provides the runnable/present quants; expanding a family lists the
    other quants its HF repo offers (downloadable). The header shows how many challenges will run."""
    CSS = """
    ModelsScreen { align: center middle; }
    #models { width: 92; height: 26; border: thick $accent; background: $surface; padding: 1; }
    #models-tree { height: 1fr; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("a", "add", "Add"),
                ("r", "run", "Run"), ("k", "ctx", "Context"),
                ("t", "reasoning", "Think"), ("b", "budget", "Budget"), ("v", "quants", "Quants"),
                ("u", "queue", "Queue"), ("U", "unload", "Unload VRAM"), ("x", "delete", "Delete")]

    def _header(self) -> str:
        ids, lvl = self.app.run_ids(), self.app.selected_level
        scope = f"level [b]{lvl}[/]" if lvl else f"[b]{len(ids)}[/] challenges"
        e = self._target_entry()
        cur = self.app.ctx_for(e.name) if e else self.app.ctx_overrides.get("")
        who = e.name if e else "default"
        ctx = f"[b]{_ctx_k(cur)}[/] ({who})" if cur else f"[b]default[/] ({who})"
        rsn = self.app.reasoning_for(e.name) if e else self.app.reasoning_overrides.get("")
        think = f"  ·  think [b]{_think_label(rsn)}[/]" if rsn is not None else ""
        bdg = self.app.budget_for(e.name) if e else self.app.budget_overrides.get("")
        budget = f"  ·  budget [b]{_ctx_k(bdg)}[/]" if bdg else ""
        return (f"[b]Models[/b] — will run {scope} @ ctx {ctx}{think}{budget}  ·  ⏎ expand · download · run  "
                "·  r run · k ctx · t think · b budget · v quants · a add · x del · u queue · Esc")

    def compose(self) -> ComposeResult:
        with Vertical(id="models"):
            yield Static(self._header(), id="models-hdr")
            yield ModelTree("models", id="models-tree")

    def _refresh_header(self) -> None:
        self.query_one("#models-hdr", Static).update(self._header())

    def on_tree_node_highlighted(self, _ev) -> None:
        self._refresh_header()          # the ctx shown follows the model under the cursor

    def action_ctx(self) -> None:
        e = self._target_entry()
        key = e.name if e else ""
        self.app.push_screen(
            CtxScreen(e, key, self.app.ctx_overrides.get(key)),
            lambda _=None: self._refresh_header())

    def action_reasoning(self) -> None:
        e = self._target_entry()
        key = e.name if e else ""
        self.app.push_screen(
            ReasoningScreen(e, key, self.app.reasoning_overrides.get(key)),
            lambda _=None: self._refresh_header())

    def action_budget(self) -> None:
        e = self._target_entry()
        key = e.name if e else ""
        self.app.push_screen(
            BudgetScreen(e, key, self.app.budget_overrides.get(key)),
            lambda _=None: self._refresh_header())

    def on_mount(self) -> None:
        tree = self.query_one("#models-tree", Tree)
        tree.show_root = False
        tree.auto_expand = False
        self._leaderboard = None
        self.refresh_models()      # registry-only first (instant, offline-safe)
        self.load_remote()         # then merge in models the server has run on similar hardware
        tree.focus()

    def _last_tps(self, name: str):
        for h in reversed(history.load()):
            if h.get("model") == name and h.get("your_tps"):
                return h["your_tps"]
        return None

    def _best_local_tps(self, entries):
        vals = [t for e in entries if (t := self._last_tps(e.name))]
        return max(vals) if vals else None

    @staticmethod
    def _fitmark(size, max_vram) -> str:
        if not size:
            return "?"
        return "✓" if (max_vram and size <= max_vram) else "✗"

    def _merged_families(self, leaderboard) -> list[dict]:
        """Registry families merged with leaderboard families (models others ran on hardware that fits
        ours), each annotated with a claimed tps. Sorted by that tps so the fastest-on-similar-hardware
        models lead; remote-only families (not in the registry) are downloadable."""
        fams: dict[str, dict] = {}
        for fam, entries in models.group_by_family(models.load_registry()).items():
            fams[fam] = {"family": fam, "entries": entries, "remote": False,
                         "repo": next((e.repo for e in entries if e.repo), None),
                         "tps": self._best_local_tps(entries), "hw": None}
        for row in (leaderboard or {}).get("leaderboard", []):
            name = row.get("family")
            if not name:
                continue
            run = row.get("run", {})
            f = fams.get(name) or fams.setdefault(name, {"family": name, "entries": [], "remote": True,
                                                          "repo": None, "tps": None, "hw": None})
            tps = row.get("tok_per_s")
            if tps is not None and (f["tps"] is None or f["remote"]):   # prefer the server's claimed tps
                f["tps"], f["hw"] = tps, run.get("vram_gb")
            f["repo"] = f["repo"] or run.get("hf_repo")
        return sorted(fams.values(), key=lambda f: (f["tps"] is None, -(f["tps"] or 0), f["family"]))

    def _family_label(self, f: dict, n_hf: int | None = None) -> str:
        tps = f.get("tps")
        tps_s = (f" · [b]{tps:.0f}[/] tps" + (f"@{f['hw']:.0f}GB" if f.get("hw") else "")) if tps else ""
        if f["remote"] and not f["entries"]:
            tag = f"(remote · {n_hf} quants" + ")" if n_hf else "(remote · ⏎ to see quants)"
        else:
            extra = f", +{n_hf} on HF" if n_hf else ""
            tag = f"({len(f['entries'])} local{extra})"
        return f"[b]{f['family']}[/]{tps_s}  {tag}"

    def _registry_label(self, e, max_vram) -> str:
        present = "✓" if e.present else "·"
        size = f"{e.size_gb} GB" if e.size_gb else "—"
        tps = self._last_tps(e.name)
        caps = eng_caps.effective_capabilities(e.name)
        caps_s = "".join(c for c, on in [("T", "tools" in caps), ("A", "agentic" in caps),
                                         ("R", "reasoner" in caps)] if on) or "-"
        return (f"{present} {e.quant:13} {size:>8}  {self._fitmark(e.size_gb, max_vram)}fit  "
                f"{(f'{tps:.0f} tps' if tps else '—'):>8}  {caps_s}")

    def _hf_label(self, q, max_vram) -> str:
        sz = q.get("size_gb")
        size = f"~{sz} GB" if sz else "—"
        return f"· {q['quant']:13} {size:>8}  {self._fitmark(sz, max_vram)}fit  (download)"

    def refresh_models(self, leaderboard=None) -> None:
        tree = self.query_one("#models-tree", Tree)
        tree.clear()
        max_vram = hardware.snapshot().max_vram_gb
        for f in self._merged_families(leaderboard):
            entries = f["entries"]
            present = next((e for e in entries if e.present), None)
            node = tree.root.add(self._family_label(f),
                                 data={"kind": "family", "f": f, "family": f["family"], "repo": f["repo"],
                                       "entries": entries, "entry": present or (entries[0] if entries else None),
                                       "remote": f["remote"], "hf_done": False})
            for e in entries:
                node.add_leaf(self._registry_label(e, max_vram), data={"kind": "registry", "entry": e})
            # families start collapsed — expand (⏎ or →) to see quants; HF discovery runs on expand
        if tree.root.children:
            tree.cursor_line = 0

    @work(thread=True, exclusive=True)
    def load_remote(self) -> None:
        try:
            lb = client.get_leaderboard(self.app.base_url, max_vram_gb=hardware.snapshot().max_vram_gb,
                                        sort="tok_per_s")
        except Exception:  # noqa: BLE001 — offline / no server: stay registry-only
            return
        self._leaderboard = lb
        n = lb.get("count", 0)
        self.app.call_from_thread(self.refresh_models, lb)
        if n:
            self.app.call_from_thread(self.app.notify,
                                      f"{n} model(s) with runs on hardware ≤ yours, sorted by tps")

    def on_tree_node_expanded(self, ev: "Tree.NodeExpanded") -> None:
        d = ev.node.data or {}
        if d.get("kind") == "family" and d.get("repo") and not d.get("hf_done"):
            d["hf_done"] = True   # set now so a quick re-expand doesn't double-fetch
            self.discover_hf(ev.node)

    @work(thread=True)
    def discover_hf(self, node) -> None:
        d = node.data or {}
        quants = models.available_quants(d["repo"])
        have = {e.quant for e in d["entries"]}
        extra = [q for q in quants if q["quant"] not in have]
        if extra:
            self.app.call_from_thread(self._add_hf, node, extra)

    def _add_hf(self, node, extra) -> None:
        max_vram = hardware.snapshot().max_vram_gb
        d = node.data
        for q in extra:
            node.add_leaf(self._hf_label(q, max_vram),
                          data={"kind": "hf", "family": d["family"], "repo": d["repo"],
                                "file": q["file"], "quant": q["quant"], "size_gb": q.get("size_gb")})
        node.set_label(self._family_label(d["f"], len(extra)))

    def _node_data(self) -> dict:
        try:                                   # the header reads this during compose, before the tree mounts
            n = self.query_one("#models-tree", Tree).cursor_node
        except Exception:  # noqa: BLE001
            return {}
        return (n.data if n else None) or {}

    def _target_entry(self):
        """The registry entry to act on: a quant leaf's entry, or a family's present/first quant."""
        d = self._node_data()
        return d.get("entry") if d.get("kind") in ("registry", "family") else None

    def action_delete(self) -> None:
        """Delete the highlighted model's downloaded GGUF from disk (confirmed)."""
        e = self._target_entry()
        if not (e and e.present):
            self.notify("no downloaded model under the cursor to delete")
            return
        size = f" · {e.size_gb} GB" if e.size_gb else ""

        def do_delete() -> None:
            if models.delete_model(e):
                self.notify(f"deleted {e.name} {e.quant}{size}")
                self.refresh_models()
            else:
                self.notify("delete failed", severity="error")

        self.app.push_screen(ConfirmScreen(
            f"Delete [b]{e.name}[/] {e.quant}{size} from disk?\n"
            "The GGUF file is removed (re-download anytime); the registry entry stays.",
            do_delete))

    def action_queue(self) -> None:
        self.app.push_screen(QueueScreen())

    @work(thread=True, exclusive=True, group="unload")
    def action_unload(self) -> None:
        """Free VRAM by unloading the gateway's currently-loaded model (refused while a run holds it).
        Off-thread because stopping llama-server can take a moment; the hardware panel updates itself."""
        try:
            ok, detail = client.unload_model()
        except client.APIError as e:   # daemon unreachable — notify, don't let the worker crash the app
            ok, detail = False, f"unload failed: {e}"
        self.app.call_from_thread(self.notify, detail, severity="information" if ok else "warning")

    def action_quants(self) -> None:
        d = self._node_data()
        if d.get("kind") == "registry":
            e = d["entry"]
            fam, repo = e.fam, e.repo
        else:
            fam, repo = d.get("family"), d.get("repo")
        if fam:
            self.app.push_screen(QuantScreen(fam, self.app.base_url, repo=repo))

    def action_run(self) -> None:
        """Run the selected quant (download first if needed) — a real, submittable run."""
        e = self._target_entry()
        if not e:
            self.notify("pick a registered quant — ⏎ an HF quant to download + run it")
            return
        run_with_preflight(self, e.name, challenge_ids=self.app.run_ids(), level=self.app.selected_level)

    def action_enter(self) -> None:
        """⏎ on a quant: run it if it's downloaded; otherwise confirm, then queue a download+run job."""
        d = self._node_data()
        if d.get("kind") == "registry":
            e = d["entry"]
            if e.present:
                self._run(e.name)
            else:
                self._confirm_download_run(e.quant, name=e.name)
        elif d.get("kind") == "hf":
            self._confirm_download_run(d["quant"], register=(d["family"], d["repo"], d["file"], d["quant"]))

    def _run(self, name: str) -> None:
        run_with_preflight(self, name, challenge_ids=self.app.run_ids(), level=self.app.selected_level)

    def _confirm_download_run(self, label: str, *, name: str | None = None, register=None) -> None:
        def go() -> None:
            nm = name
            if register is not None:                 # HF-only quant: register it so it can be served
                try:
                    nm = models.register_quant(*register).name
                except Exception as ex:  # noqa: BLE001
                    self.notify(f"register failed: {ex}")
                    return
            self._run(nm)                            # reproduce downloads (as part of the queued job) then runs
        self.app.push_screen(ConfirmScreen(
            f"[b]{label}[/] isn't downloaded. Download and run it?\nThe download runs as a queued job.", go))


class ChallengesScreen(ModalScreen):
    """Browse challenges by family → month → challenge and pick a set to run. Selecting everything
    (press `a`) then running is the full-suite run; any subset is just as easy."""
    CSS = """
    ChallengesScreen { align: center middle; }
    #challenges { width: 98; height: 32; border: thick $accent; background: $surface; padding: 1; }
    #ch-tree { height: 1fr; }
    #ch-status { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("a", "all", "All"),
                ("c", "clear", "Clear"), ("r", "run", "Run"),
                ("1", "select_level(0)", "smoke"), ("2", "select_level(1)", "quick"),
                ("3", "select_level(2)", "standard"), ("4", "select_level(3)", "deep"),
                ("5", "select_level(4)", "max")]

    def __init__(self):
        super().__init__()
        self.sel = ch_browse.Selection()
        self._all_ids: list[str] = []
        self._corpus: list = []
        self._levels: dict = {}
        self._level_names: list[str] = []
        self._chosen_level: str | None = None   # set by a level shortcut; cleared on manual edit

    def compose(self) -> ComposeResult:
        with Vertical(id="challenges"):
            yield Static("[b]Challenges[/b]  ·  [b]1-5[/] level (smoke→max)  ·  space select  ·  ⏎/→ expand  ·  ← collapse  "
                         "·  a all  ·  c clear  ·  r run  ·  Esc close")
            yield NavTree("challenges", id="ch-tree")
            yield Static("", id="ch-status")

    def on_mount(self) -> None:
        tree = self.query_one("#ch-tree", NavTree)
        tree.auto_expand = False   # selection (space) never auto-expands; ⏎/→ expand, ← collapse
        tree.focus()
        try:
            corpus = ch_browse.load_corpus()
        except Exception as e:  # noqa: BLE001
            self.query_one("#ch-status", Static).update(f"[red]could not load corpus: {e}[/]")
            return
        self._corpus = corpus
        try:
            _, self._levels = eng_levels.load_levels()
            self._level_names = list(self._levels)
        except Exception:  # noqa: BLE001 — level shortcuts just stay inert if levels.toml is unreadable
            self._levels, self._level_names = {}, []
        self._all_ids = [c.id for c in corpus]
        root = tree.root
        root.data = {"ids": self._all_ids, "base": f"All challenges ({len(corpus)})", "kind": "root"}
        for grp in ch_browse.group_by_collection(corpus):
            chs = grp["chs"]
            ids = [c.id for c in chs]
            if grp["kind"] == "native":   # our challenges: collection -> date -> language/axis family -> challenges
                node = root.add("", data={"ids": ids, "base": f"{grp['label']} ({len(chs)})", "kind": "native"})
                for bucket, dchs in ch_browse.group_by_date(chs).items():
                    dnode = node.add("", data={"ids": [c.id for c in dchs], "base": f"{bucket} ({len(dchs)})"})
                    for family, fchs in ch_browse.group_by_family(dchs).items():
                        dnode.add("", data={"ids": [c.id for c in fchs], "base": f"{family} ({len(fchs)})",
                                            "chs": fchs, "filled": False})
            else:                          # imported suite: suite -> month -> challenges
                node = root.add("", data={"ids": ids, "base": f"{grp['label']} ({len(chs)})", "kind": "suite"})
                for bucket, dchs in ch_browse.group_by_date(chs).items():
                    node.add("", data={"ids": [c.id for c in dchs], "base": f"{bucket} ({len(dchs)})",
                                       "chs": dchs, "filled": False})
        root.expand()
        self._refresh()
        # open ready-to-run on the official 'standard' level (press 1/2/4/5 or edit to change)
        if "standard" in self._level_names:
            self.action_select_level(self._level_names.index("standard"))

    def on_tree_node_expanded(self, ev: "Tree.NodeExpanded") -> None:
        d = ev.node.data or {}
        if d.get("chs") is not None and not d.get("filled"):   # a date node — fill challenge leaves once
            for c in d["chs"]:
                ev.node.add_leaf("", data={"ids": [c.id], "base": f"{c.id} — {c.title}"})
            d["filled"] = True
            self._refresh()

    def _walk(self, node):
        yield node
        for c in node.children:
            yield from self._walk(c)

    @staticmethod
    def _level_tags(level) -> str:
        """Compact run-settings caption for a level, e.g. 'judge·agent·prebuilt'."""
        tags = [t for t, on in [("judge", level.judge), ("agent", level.agent),
                                ("prebuilt", level.prebuilt), ("retry", level.retries)] if on]
        return "·".join(tags)

    def _refresh(self) -> None:
        tree = self.query_one("#ch-tree", Tree)
        for node in self._walk(tree.root):
            if node.data:
                node.set_label(f"{ch_browse.MARKER[self.sel.state(node.data['ids'])]} {node.data['base']}")
        n, total = len(self.sel.ids), len(self._all_ids)
        if self._chosen_level:
            tags = self._level_tags(self._levels[self._chosen_level])
            scope = f"level [b]{self._chosen_level}[/]" + (f" ({tags})" if tags else "")
        else:
            scope = "custom selection" if n else ""
        eta = ch_browse.rough_eta(n)
        self.query_one("#ch-status", Static).update(
            f"[b]{n}[/] / {total} selected" + (f"  ·  {scope}" if scope else "")
            + (f"  ·  {eta} @ 1/s" if eta else "")
            + ("  ·  press [b]r[/] to run" if n else ""))

    def action_select_level(self, idx: int) -> None:
        """Load a level's exact bench selection (1=smoke … 5=max), ready to run with its settings."""
        if idx >= len(self._level_names):
            self.notify("no such level")
            return
        name = self._level_names[idx]
        ids = eng_levels.resolve(self._levels[name], self._corpus)
        if not ids:
            self.notify(f"{name}: no matching challenges in the current corpus")
            return
        self.sel.ids = set(ids)
        self._chosen_level = name
        self._refresh()
        tags = self._level_tags(self._levels[name])
        self.notify(f"{name}: {len(ids)} challenges" + (f" · {tags}" if tags else "") + " — press r to run")

    def on_tree_node_selected(self, ev: "Tree.NodeSelected") -> None:
        if ev.node.data:                       # ⏎ on any node toggles its whole id-set
            self.sel.toggle(ev.node.data["ids"])
            self._chosen_level = None          # hand-edited -> custom selection, not a level
            self._refresh()

    def action_all(self) -> None:
        self.sel.ids = set(self._all_ids)
        self._chosen_level = None
        self._refresh()

    def action_clear(self) -> None:
        self.sel.ids = set()
        self._chosen_level = None
        self._refresh()

    def action_run(self) -> None:
        ids = self.sel.resolve()
        if not ids:
            self.notify("select at least one challenge (1-5 for a level, space to pick, or a for all)")
            return
        self.app.selected_ids = ids
        self.app.selected_level = self._chosen_level   # level run (settings apply) vs plain id run
        scope = f"level {self._chosen_level}" if self._chosen_level else f"{len(ids)} challenges"
        self.notify(f"{scope} selected — pick a model to run")
        self.dismiss()
        self.app.push_screen(ModelsScreen())


class QuantScreen(ModalScreen):
    """Compare a model family's quants side by side: every quant it has — downloaded (✓), registered,
    or just available on HF (·) — with leaderboard scores where someone has run it. Download the
    highlighted quant with `d`. Merges the local registry, the HF repo listing, and the API."""
    CSS = """
    QuantScreen { align: center middle; }
    #quants { width: 104; height: 24; border: thick $accent; background: $surface; padding: 1; }
    #q-tbl { height: 1fr; }
    #q-note { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("d", "download", "Download")]

    def __init__(self, family: str, base_url: str, repo: str | None = None):
        super().__init__()
        self.family = family
        self.base_url = base_url
        self.repo = repo
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="quants"):
            yield Static(f"[b]Quants[/b] for {self.family}  ·  d download  ·  Esc close")
            yield DataTable(id="q-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("loading…", id="q-note")

    def on_mount(self) -> None:
        self.query_one("#q-tbl", DataTable).add_columns(
            "Quant", "State", "Size", "Code", "Held-out", "Agent", "Math", "TPS", "Trust")
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        reg = {e.quant: e for e in models.load_registry().values() if e.fam == self.family}
        repo = self.repo or next((e.repo for e in reg.values() if e.repo), None)
        hf = {h["quant"]: h for h in (models.available_quants(repo) if repo else [])}
        try:
            runs = client.get_model(self.base_url, self.family).get("runs", [])
        except client.APIError:
            runs = []
        run_by_q: dict[str, dict] = {}
        for r in runs:                                   # keep the best code score per quant
            q = r.get("run", {}).get("artifact", "?")
            if q not in run_by_q or (r.get("code_score") or 0) > (run_by_q[q].get("code_score") or 0):
                run_by_q[q] = r
        rows = []
        for q in sorted(set(reg) | set(hf) | set(run_by_q)):
            e, h, run = reg.get(q), hf.get(q), run_by_q.get(q)
            present = bool(e and e.present)
            rinfo = (run or {}).get("run", {})
            rows.append({
                "quant": q,
                "state": "✓ local" if present else ("· registered" if e else "· HF"),
                "size": (f"{e.size_gb} GB" if (e and e.size_gb)
                         else f"~{h['size_gb']} GB" if (h and h.get("size_gb")) else "—"),
                "code": (run or {}).get("code_score"), "held": (run or {}).get("held_out_score"),
                "agent": (run or {}).get("agent_score"), "math": (run or {}).get("math_score"),
                "tps": (run or {}).get("tok_per_s"), "trust": (rinfo.get("trust_tier") or "").replace("-", " "),
                "present": present, "entry": e, "repo": repo, "file": h["file"] if h else None})
        self.app.call_from_thread(self._fill, rows)

    def _fill(self, rows) -> None:
        t = self.query_one("#q-tbl", DataTable)
        t.clear()
        self._rows = rows
        for r in rows:
            t.add_row(r["quant"], r["state"], r["size"], _fmt(r["code"]), _fmt(r["held"]),
                      _fmt(r["agent"]), _fmt(r["math"]), _fmt(r["tps"], "{:.0f}"), r["trust"])
        scored = sum(1 for r in rows if r["code"] is not None)
        self.query_one("#q-note", Static).update(
            f"{len(rows)} quant(s) · {scored} with leaderboard runs · ✓ local · · downloadable (d)"
            if rows else "no quants found (registry / HF / leaderboard all empty)")

    def action_download(self) -> None:
        t = self.query_one("#q-tbl", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self._rows):
            return
        row = self._rows[t.cursor_row]
        if row["present"]:
            self.notify(f"{row['quant']} already downloaded")
            return
        entry = row["entry"]
        if entry is None:                        # HF-only quant: register it so it can be served
            if not (row["repo"] and row["file"]):
                self.notify("no HF source for this quant")
                return
            try:
                entry = models.register_quant(self.family, row["repo"], row["file"], row["quant"])
            except Exception as ex:  # noqa: BLE001
                self.notify(f"register failed: {ex}")
                return
        started = self.app.start_download(entry.name)   # download runs on the daemon's download queue
        if started:
            self.notify(f"queued download: {entry.name} — open the queue (u) to watch it")
        self.app.call_from_thread(self.load)


class AddWishlistScreen(ModalScreen):
    """Add a model to the personal wishlist (name + optional HF repo + note)."""
    CSS = """
    AddWishlistScreen { align: center middle; }
    #addwish { width: 84; height: auto; border: thick $accent; background: $surface; padding: 1; }
    #addwish Input { margin-bottom: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="addwish"):
            yield Static("[b]Add to wishlist[/b]  ·  Enter save · Esc cancel")
            yield Input(placeholder="model name  e.g. qwen3-coder", id="w-name")
            yield Input(placeholder="HF repo (optional)  e.g. unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", id="w-repo")
            yield Input(placeholder="note (optional)  e.g. want its agentic score", id="w-note-in")

    def on_mount(self) -> None:
        self.query_one("#w-name", Input).focus()

    def on_input_submitted(self, _event) -> None:
        name = self.query_one("#w-name", Input).value.strip()
        if name:
            wishlist.add(name, self.query_one("#w-repo", Input).value,
                         self.query_one("#w-note-in", Input).value)
        self.dismiss(True)


class WishlistScreen(ModalScreen):
    """Personal model wishlist: models you want to test, with one-key download. `a` add, `d` download
    the highlighted model (opens its quant browser), `x` delete. Stored locally (no server/auth)."""
    CSS = """
    WishlistScreen { align: center middle; }
    #wish { width: 100; height: 22; border: thick $accent; background: $surface; padding: 1; }
    #w-tbl { height: 1fr; }
    #w-note { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("a", "add", "Add"),
                ("d", "download", "Download"), ("x", "delete", "Delete")]

    def __init__(self, base_url: str, on_board: set | None = None):
        super().__init__()
        self.base_url = base_url
        self.on_board = on_board or set()
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="wish"):
            yield Static("[b]Wishlist[/b] — models to test  ·  a add · d download · x delete · Esc close")
            yield DataTable(id="w-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("", id="w-note")

    def on_mount(self) -> None:
        self.query_one("#w-tbl", DataTable).add_columns("Model", "HF repo", "Note", "On board")
        self.refresh_list()

    def refresh_list(self) -> None:
        self._rows = wishlist.load()
        t = self.query_one("#w-tbl", DataTable)
        t.clear()
        for i in self._rows:
            done = "✓" if i.get("name") in self.on_board else ""
            t.add_row(i.get("name", ""), i.get("repo", "") or "—", i.get("note", "") or "", done)
        self.query_one("#w-note", Static).update(
            f"{len(self._rows)} model(s) · d opens the quant browser to download the highlighted one"
            if self._rows else "empty — press a to add a model you want tested")

    def _cursor(self):
        t = self.query_one("#w-tbl", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self._rows):
            return None
        return self._rows[t.cursor_row]

    def action_add(self) -> None:
        self.app.push_screen(AddWishlistScreen(), lambda _=None: self.refresh_list())

    def action_delete(self) -> None:
        row = self._cursor()
        if row:
            wishlist.remove(row.get("name", ""))
            self.refresh_list()

    def action_download(self) -> None:
        row = self._cursor()
        if not row:
            return
        if not row.get("repo"):
            self.notify("no HF repo on this entry — press x to remove and re-add with a repo")
            return
        self.app.push_screen(QuantScreen(row["name"], self.base_url, repo=row["repo"]))


class UpdateScreen(ModalScreen):
    """Popup when a newer client is available: recommends updating and offers to do it (default).
    'Update' suspends the TUI, runs the right upgrader (pipx/pip), then prompts a restart; the running
    process keeps the old code in memory until relaunched. Escape / 'Later' dismisses."""
    CSS = """
    UpdateScreen { align: center middle; }
    #upd { width: 66; height: auto; border: thick $accent; background: $surface; padding: 1 2; }
    #upd-btns { height: auto; padding-top: 1; }
    #upd-btns Button { margin-right: 2; }
    """
    BINDINGS = [("escape", "later", "Later")]

    def __init__(self, installed: str, latest: str, required: bool = False):
        super().__init__()
        self.installed = installed
        self.latest = latest
        self.required = required

    def compose(self) -> ComposeResult:
        with Vertical(id="upd"):
            if self.required:
                yield Static(f"[b red]Update required[/]\n\nThis client ([b]{self.installed}[/]) is below "
                             f"the minimum supported version ([b]{self.latest}[/]). Update to keep "
                             f"submitting runs and stay compatible with the leaderboard.")
            else:
                yield Static(f"[b]A new Peakstone version is available[/]\n\n"
                             f"[b]{self.latest}[/] is out — you have [b]{self.installed}[/].\n"
                             f"Updating is recommended. Update now?")
            with Horizontal(id="upd-btns"):
                yield Button("Update", id="update", variant="success")
                yield Button("Later", id="later")

    def on_mount(self) -> None:
        self.query_one("#update", Button).focus()   # default action → Enter updates

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "update":
            self._do_update()
        else:
            self.action_later()

    def action_later(self) -> None:
        self.dismiss(False)

    def _do_update(self) -> None:
        import subprocess
        import sys
        from .update import _install_kind
        kind = _install_kind()
        if kind == "editable":
            self.notify("dev/editable install — update with: git pull (then reinstall if deps changed)",
                        timeout=10)
            self.dismiss(False)
            return
        cmd = (["pipx", "upgrade", "peakstone"] if kind == "pipx"
               else [sys.executable, "-m", "pip", "install", "-U", "peakstone[dashboard]"])
        with self.app.suspend():
            print(f"\nUpdating Peakstone ({kind}) …  {' '.join(cmd)}\n")
            try:
                rc = subprocess.call(cmd)
            except FileNotFoundError as e:
                print(f"could not run the upgrader ({e}); try `peakstone update` manually.")
                rc = 1
            input("\n(press Enter to return to the dashboard)")
        if rc == 0:
            self.notify("updated ✓ — quit (q) and relaunch to use the new version",
                        severity="information", timeout=15)
        else:
            self.notify("update failed — run `peakstone update` in a terminal", severity="error",
                        timeout=10)
        self.dismiss(rc == 0)


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

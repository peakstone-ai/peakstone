"""Peakstone dashboard (Textual TUI) — live local hardware + a leaderboard browser auto-filtered to
what fits your GPU, so you can see how models that run on YOUR hardware compare (and at what TPS).

Run:  peakstone            (or)  python -m dashboard  [--api URL]
"""
from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, ProgressBar, RichLog, Static, Tree

from peakstone.engine import capabilities as eng_caps
from peakstone.engine import estimate as eng_estimate
from peakstone.engine import levels as eng_levels

from . import challenges as ch_browse
from . import client, hardware, history, models, preflight, reproduce

# a short, fast challenge set for a reproduce run — enough to measure tok/s + a code score
REPRODUCE_IDS = ["py-02-csv-groupby", "py-05-calc", "py-01-fizzbuzz"]


def _bar(used: int, total: int, width: int = 22) -> str:
    frac = (used / total) if total else 0.0
    filled = int(frac * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {used:,}/{total:,}"


def _fmt(v, fmt: str = "{:.2f}") -> str:
    return fmt.format(v) if isinstance(v, (int, float)) else "—"


class HardwarePanel(Static):
    """Live GPU/CPU/RAM meters, refreshed every second."""

    def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh_stats)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        s = hardware.snapshot()
        lines = []
        for g in s.gpus:
            lines.append(f"[b]GPU{g.index}[/b] {g.name}  ([b]{g.vram_gb:g} GB[/b])")
            lines.append(f"  VRAM {_bar(g.mem_used_mib, g.mem_total_mib)} MiB   util {g.util_pct}%")
        if not s.gpus:
            lines.append("[yellow]No GPU detected — CPU only[/yellow]")
        lines.append(f"[b]CPU[/b]  {s.cpu_pct:5.1f}%  ({s.cores} cores)")
        lines.append(f"[b]RAM[/b]  {_bar(s.ram_used_mib, s.ram_total_mib)} MiB")
        self.update("\n".join(lines))


class Dashboard(App):
    CSS = """
    HardwarePanel { height: auto; border: round $accent; padding: 0 1; margin: 1 1 0 1; }
    DataTable { height: 1fr; margin: 0 1; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("f", "toggle_fit", "Fit filter"),
        ("s", "cycle_sort", "Sort axis"),
        ("enter", "reproduce", "Reproduce"),
        ("c", "challenges", "Peakstones"),
        ("v", "quants", "Quants"),
        ("m", "models", "Models"),
        ("h", "history", "History"),
    ]
    SORTS = ["code_score", "held_out_score", "agent_score", "planner_score", "tok_per_s"]

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.fit = True          # filter to models that fit my VRAM
        self.sort_i = 0
        self._board_rows: list[dict] = []
        # peakstones chosen in the Challenges screen; empty = use the quick default repro set.
        self.selected_ids: list[str] = []
        # set when the selection came from a level shortcut (1-5) — runs via --level so the level's
        # judge/agent/prebuilt settings apply; None for a hand-picked selection (plain id run).
        self.selected_level: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield HardwarePanel()
        yield DataTable(zebra_stripes=True, cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Peakstone"
        table = self.query_one(DataTable)
        table.add_columns("#", "Model", "Code", "Agentic", "Planner", "TPS", "VRAM", "Trust")
        self.load_board()

    def action_refresh(self) -> None:
        self.load_board()

    def action_toggle_fit(self) -> None:
        self.fit = not self.fit
        self.load_board()

    def action_cycle_sort(self) -> None:
        self.sort_i = (self.sort_i + 1) % len(self.SORTS)
        self.load_board()

    def action_models(self) -> None:
        self.push_screen(ModelsScreen())

    def action_history(self) -> None:
        self.push_screen(HistoryScreen())

    def action_challenges(self) -> None:
        self.push_screen(ChallengesScreen())

    def action_quants(self) -> None:
        table = self.query_one(DataTable)
        i = table.cursor_row
        if not self._board_rows or i is None or i >= len(self._board_rows):
            return
        fam = self._board_rows[i].get("family")
        if fam:
            self.push_screen(QuantScreen(fam, self.base_url))

    def run_ids(self) -> list[str]:
        """Challenges to run: the user's Challenges-screen selection, else the quick default set."""
        return self.selected_ids or REPRODUCE_IDS

    def action_reproduce(self) -> None:
        table = self.query_one(DataTable)
        i = table.cursor_row
        if not self._board_rows or i is None or i >= len(self._board_rows):
            return
        row = self._board_rows[i]
        if not row.get("family"):
            return
        self.push_screen(ReproduceScreen(row["family"], row.get("tok_per_s"), self.base_url,
                                         challenge_ids=self.run_ids()))

    @work(thread=True, exclusive=True)
    def load_board(self) -> None:
        snap = hardware.snapshot()
        max_vram = snap.max_vram_gb if (self.fit and snap.max_vram_gb) else None
        try:
            data = client.get_leaderboard(self.base_url, max_vram_gb=max_vram, sort=self.SORTS[self.sort_i])
        except client.APIError as e:
            self.call_from_thread(self._render_error, str(e))
            return
        self.call_from_thread(self._render, data, max_vram)

    def _render(self, data: dict, max_vram: float | None) -> None:
        table = self.query_one(DataTable)
        table.clear()
        scope = f"fits ≤{max_vram:g} GB" if max_vram else "all hardware"
        sel = f"  ·  ▶ {len(self.selected_ids)} peakstones selected" if self.selected_ids else ""
        self.sub_title = (f"{self.base_url}  ·  {scope}  ·  sort: {self.SORTS[self.sort_i]}  ·  "
                          f"⏎ reproduce  v quants  c peakstones  m models{sel}")
        rows = data.get("leaderboard", [])
        self._board_rows = rows
        for r in rows:
            run = r.get("run", {})
            table.add_row(
                str(r.get("rank", "")), r.get("family", ""),
                _fmt(r.get("code_score")), _fmt(r.get("agent_score")), _fmt(r.get("planner_score")),
                _fmt(r.get("tok_per_s"), "{:.0f}"),
                f"{run.get('vram_gb', '?')} GB", (run.get("trust_tier") or "").replace("-", " "))
        if not rows:
            table.add_row("", "(no runs fit this filter)", "", "", "", "", "", "")

    def _render_error(self, msg: str) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self.sub_title = f"{self.base_url}  ·  API unreachable"
        table.add_row("", "API unreachable", msg[:50], "", "", "", "", "")


class ReproduceScreen(ModalScreen):
    """Reproduce a model on local hardware and compare your tok/s to the published number."""
    CSS = """
    ReproduceScreen { align: center middle; }
    #repro { width: 84; height: 24; border: thick $accent; background: $surface; padding: 1; }
    #repro-log { height: 1fr; border: round $primary; }
    #repro-result { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("s", "submit", "Submit")]

    def __init__(self, model: str, published_tps: float | None, base_url: str,
                 challenge_ids: list[str] | None = None, level: str | None = None, free_procs=None):
        super().__init__()
        self.model = model
        self.published_tps = published_tps
        self.base_url = base_url
        self.level = level
        self.challenge_ids = challenge_ids or REPRODUCE_IDS
        self.free_procs = free_procs or []   # llama-servers to free before serving (pre-flight)
        self._result: reproduce.ReproduceResult | None = None

    def compose(self) -> ComposeResult:
        scope = f"level {self.level}" if self.level else f"{len(self.challenge_ids)} peakstones"
        with Vertical(id="repro"):
            yield Static(f"[b]Run[/b] {self.model}  ·  {scope}  ·  "
                         f"published {_fmt(self.published_tps, '{:.0f}')} tok/s", id="repro-title")
            yield RichLog(id="repro-log", wrap=True, max_lines=300)
            yield Static("running… (Esc to close)", id="repro-result")

    def on_mount(self) -> None:
        self.run_reproduce()

    @work(thread=True, exclusive=True)
    def run_reproduce(self) -> None:
        log = self.query_one("#repro-log", RichLog)

        def emit(s: str) -> None:
            self.app.call_from_thread(log.write, s)

        if self.free_procs:
            emit(f"freeing GPU: stopping {len(self.free_procs)} llama-server process(es)…")
            preflight.free(self.free_procs)
        res = reproduce.reproduce(self.model, challenge_ids=self.challenge_ids, level=self.level,
                                  published_tps=self.published_tps, log=emit)
        history.append({"model": res.model, "ok": res.ok, "your_tps": res.your_tps,
                        "published_tps": res.published_tps, "code_score": res.code_score, "note": res.note})
        self.app.call_from_thread(self._show, res)

    def _show(self, res: "reproduce.ReproduceResult") -> None:
        self._result = res
        out = self.query_one("#repro-result", Static)
        if res.ok:
            ratio = f"  ([b]{res.tps_ratio}×[/b] published)" if res.tps_ratio else ""
            submit_hint = "  ·  press [b]s[/] to submit" if res.bundle else ""
            out.update(f"[green b]done[/]  ·  your [b]{_fmt(res.your_tps, '{:.0f}')}[/] tok/s vs published "
                       f"{_fmt(res.published_tps, '{:.0f}')}{ratio}  ·  code {_fmt(res.code_score)} "
                       f"({res.passed}/{res.total}){submit_hint}")
        else:
            out.update(f"[red b]failed[/] — {res.note}")

    def action_submit(self) -> None:
        if not (self._result and self._result.ok and self._result.bundle):
            self.notify("nothing to submit yet")
            return
        self.submit_run()

    @work(thread=True, exclusive=True)
    def submit_run(self) -> None:
        try:
            status, detail = client.submit_bundle(self.base_url, self._result.bundle)
        except client.APIError as e:
            self.app.call_from_thread(self.app.notify, f"submit failed: {e}", severity="error")
            return
        msg = {201: "submitted ✓", 409: "already submitted", 400: "rejected"}.get(status, f"status {status}")
        self.app.call_from_thread(self.app.notify, f"{msg}")


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


def run_with_preflight(screen, name: str, *, challenge_ids=None, level=None) -> None:
    """Launch a reproduce run, first checking free accelerator memory. If a model won't fit, prompt to
    free our llama-servers (or run anyway) before opening the run; otherwise launch straight away."""
    app = screen.app
    entry = models.load_registry().get(name)
    pf = preflight.check(entry) if entry else None

    def launch(free_first: bool) -> None:
        procs = pf.freeable if (free_first and pf) else None
        app.push_screen(ReproduceScreen(name, None, app.base_url, challenge_ids=challenge_ids,
                                        level=level, free_procs=procs))

    if pf and not pf.fits_now:
        app.push_screen(PreflightScreen(name, pf, on_proceed=launch))
    else:
        launch(False)


class ModelsScreen(ModalScreen):
    """Pick a model to run the selected peakstones on. Models are grouped as family → quant: the
    registry (serve/models.toml) provides the runnable/present quants; expanding a family lists the
    other quants its HF repo offers (downloadable). The header shows how many peakstones will run."""
    CSS = """
    ModelsScreen { align: center middle; }
    #models { width: 92; height: 26; border: thick $accent; background: $surface; padding: 1; }
    #models-tree { height: 1fr; }
    #dl-bar { margin-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("a", "add", "Add"),
                ("d", "download", "Download"), ("l", "levels", "Levels"), ("r", "run", "Run")]

    def compose(self) -> ComposeResult:
        ids, lvl = self.app.run_ids(), self.app.selected_level
        scope = f"level [b]{lvl}[/]" if lvl else f"[b]{len(ids)}[/] peakstones"
        with Vertical(id="models"):
            yield Static(f"[b]Models[/b] — will run {scope}  ·  space expand  ·  r run  ·  l levels  "
                         "·  d download  ·  a add  ·  Esc close")
            yield Tree("models", id="models-tree")
            yield ProgressBar(id="dl-bar", show_eta=False)

    def on_mount(self) -> None:
        self.query_one("#dl-bar", ProgressBar).display = False
        tree = self.query_one("#models-tree", Tree)
        tree.show_root = False
        tree.auto_expand = False
        self.refresh_models()
        tree.focus()

    def _last_tps(self, name: str):
        for h in reversed(history.load()):
            if h.get("model") == name and h.get("your_tps"):
                return h["your_tps"]
        return None

    @staticmethod
    def _fitmark(size, max_vram) -> str:
        if not size:
            return "?"
        return "✓" if (max_vram and size <= max_vram) else "✗"

    def _family_label(self, fam: str, n_local: int, n_hf: int | None = None) -> str:
        extra = f", +{n_hf} on HF" if n_hf else ""
        return f"[b]{fam}[/]  ({n_local} local{extra})"

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

    def refresh_models(self) -> None:
        tree = self.query_one("#models-tree", Tree)
        tree.clear()
        max_vram = hardware.snapshot().max_vram_gb
        for fam, entries in models.group_by_family(models.load_registry()).items():
            repo = next((e.repo for e in entries if e.repo), None)
            present = next((e for e in entries if e.present), None)
            node = tree.root.add(self._family_label(fam, len(entries)),
                                 data={"kind": "family", "family": fam, "repo": repo,
                                       "entries": entries, "entry": present or entries[0], "hf_done": False})
            for e in entries:
                node.add_leaf(self._registry_label(e, max_vram), data={"kind": "registry", "entry": e})
        if tree.root.children:
            tree.cursor_line = 0

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
        node.set_label(self._family_label(d["family"], len(d["entries"]), len(extra)))

    def _node_data(self) -> dict:
        n = self.query_one("#models-tree", Tree).cursor_node
        return (n.data if n else None) or {}

    def _target_entry(self):
        """The registry entry to act on: a quant leaf's entry, or a family's present/first quant."""
        d = self._node_data()
        return d.get("entry") if d.get("kind") in ("registry", "family") else None

    def action_add(self) -> None:
        self.app.push_screen(AddModelScreen(), lambda _ok: self.refresh_models())

    def action_run(self) -> None:
        """Benchmark the selected quant locally (download if needed) → a real, submittable run. No
        published baseline since this isn't a leaderboard row; press `s` in the run view to submit."""
        e = self._target_entry()
        if not e:
            self.notify("pick a registered quant — press d to download an HF-only quant first")
            return
        run_with_preflight(self, e.name, challenge_ids=self.app.run_ids(), level=self.app.selected_level)

    def action_levels(self) -> None:
        e = self._target_entry()
        if e:
            self.app.push_screen(LevelScreen(e.name, self.app.base_url))

    def action_download(self) -> None:
        d = self._node_data()
        if d.get("kind") == "hf":
            self.download_hf(d)
        elif d.get("entry"):
            self.download_model(d["entry"].name)

    @work(thread=True, exclusive=True)
    def download_hf(self, d: dict) -> None:
        try:
            e = models.register_quant(d["family"], d["repo"], d["file"], d["quant"])
        except Exception as ex:  # noqa: BLE001
            self.app.call_from_thread(self.app.notify, f"register failed: {ex}")
            return
        self._download_entry(e)

    @work(thread=True, exclusive=True)
    def download_model(self, name: str) -> None:
        entry = models.load_registry().get(name)
        if entry:
            self._download_entry(entry)
        else:
            self.app.call_from_thread(self.refresh_models)

    def _download_entry(self, entry) -> None:
        self.app.call_from_thread(self.app.notify, f"downloading {entry.name}…")
        self.app.call_from_thread(self._bar_show, True)
        models.download(entry, lambda s: self.app.call_from_thread(self.app.notify, s, timeout=8),
                        progress=lambda done, total: self.app.call_from_thread(self._bar_update, done, total))
        self.app.call_from_thread(self._bar_show, False)
        self.app.call_from_thread(self.refresh_models)

    def _bar_show(self, show: bool) -> None:
        self.query_one("#dl-bar", ProgressBar).display = show

    def _bar_update(self, done: int, total: int | None) -> None:
        bar = self.query_one("#dl-bar", ProgressBar)
        if total:
            bar.update(total=total, progress=done)


class HistoryScreen(ModalScreen):
    CSS = """
    HistoryScreen { align: center middle; }
    #history { width: 96; height: 22; border: thick $accent; background: $surface; padding: 1; }
    #hist-tbl { height: 1fr; }
    """
    BINDINGS = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="history"):
            yield Static("[b]Reproduce history[/b]  ·  Esc close")
            yield DataTable(id="hist-tbl", zebra_stripes=True)

    def on_mount(self) -> None:
        t = self.query_one("#hist-tbl", DataTable)
        t.add_columns("When", "Model", "Your TPS", "Published", "Code", "Result")
        rows = list(reversed(history.load()))
        for h in rows:
            t.add_row(h.get("at", ""), h.get("model", ""),
                      _fmt(h.get("your_tps"), "{:.0f}"), _fmt(h.get("published_tps"), "{:.0f}"),
                      _fmt(h.get("code_score")), "ok" if h.get("ok") else (h.get("note") or "fail")[:24])
        if not rows:
            t.add_row("", "(no reproduce runs yet)", "", "", "", "")


class ChallengesScreen(ModalScreen):
    """Browse peakstones by family → month → challenge and pick a set to run. Selecting everything
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
            yield Static("[b]Peakstones[/b]  ·  [b]1-5[/] level (smoke→max)  ·  ⏎ select  ·  space expand  "
                         "·  a all  ·  c clear  ·  r run  ·  Esc close")
            yield Tree("peakstones", id="ch-tree")
            yield Static("", id="ch-status")

    def on_mount(self) -> None:
        tree = self.query_one("#ch-tree", Tree)
        tree.auto_expand = False   # so ⏎ only selects (no expand side-effect); space expands
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
        root.data = {"ids": self._all_ids, "base": f"All peakstones ({len(corpus)})", "kind": "root"}
        for grp in ch_browse.group_by_collection(corpus):
            chs = grp["chs"]
            ids = [c.id for c in chs]
            if grp["kind"] == "native":   # our peakstones: collection -> language/axis family -> challenges
                span = ch_browse.date_span(chs)
                label = f"{grp['label']}" + (f" · {span}" if span else "") + f" ({len(chs)})"
                node = root.add("", data={"ids": ids, "base": label, "kind": "native"})
                for family, fchs in ch_browse.group_by_family(chs).items():
                    node.add("", data={"ids": [c.id for c in fchs], "base": f"{family} ({len(fchs)})",
                                       "chs": fchs, "filled": False})
            else:                          # imported suite: suite -> month -> challenges
                node = root.add("", data={"ids": ids, "base": f"{grp['label']} ({len(chs)})", "kind": "suite"})
                for bucket, dchs in ch_browse.group_by_date(chs).items():
                    node.add("", data={"ids": [c.id for c in dchs], "base": f"{bucket} ({len(dchs)})",
                                       "chs": dchs, "filled": False})
        root.expand()
        self._refresh()

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
            self.notify(f"{name}: no matching peakstones in the current corpus")
            return
        self.sel.ids = set(ids)
        self._chosen_level = name
        self._refresh()
        tags = self._level_tags(self._levels[name])
        self.notify(f"{name}: {len(ids)} peakstones" + (f" · {tags}" if tags else "") + " — press r to run")

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
            self.notify("select at least one peakstone (1-5 for a level, space to pick, or a for all)")
            return
        self.app.selected_ids = ids
        self.app.selected_level = self._chosen_level   # level run (settings apply) vs plain id run
        scope = f"level {self._chosen_level}" if self._chosen_level else f"{len(ids)} peakstones"
        self.notify(f"{scope} selected — pick a model to run")
        self.dismiss()
        self.app.push_screen(ModelsScreen())


class QuantScreen(ModalScreen):
    """Compare a family's quant variants side by side: score axes vs speed vs VRAM. Pulls every run
    (no collapsing) from the API; rows that share a suite are directly comparable."""
    CSS = """
    QuantScreen { align: center middle; }
    #quants { width: 110; height: 24; border: thick $accent; background: $surface; padding: 1; }
    #q-tbl { height: 1fr; }
    #q-note { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, family: str, base_url: str):
        super().__init__()
        self.family = family
        self.base_url = base_url

    def compose(self) -> ComposeResult:
        with Vertical(id="quants"):
            yield Static(f"[b]Quants[/b] for {self.family}  ·  Esc close")
            yield DataTable(id="q-tbl", zebra_stripes=True)
            yield Static("loading…", id="q-note")

    def on_mount(self) -> None:
        self.query_one("#q-tbl", DataTable).add_columns(
            "Quant", "Suite", "Code", "Held-out", "Agent", "Math", "TPS", "VRAM", "Trust")
        self.load_quants()

    @work(thread=True, exclusive=True)
    def load_quants(self) -> None:
        try:
            data = client.get_model(self.base_url, self.family)
        except client.APIError as e:
            self.app.call_from_thread(self._note, f"API unreachable: {e}")
            return
        self.app.call_from_thread(self._fill, data.get("runs", []))

    def _fill(self, runs) -> None:
        t = self.query_one("#q-tbl", DataTable)
        t.clear()
        for r in sorted(runs, key=lambda r: (r.get("run", {}).get("artifact", ""), r.get("suite", ""))):
            run = r.get("run", {})
            t.add_row(run.get("artifact", "?"), r.get("suite", ""),
                      _fmt(r.get("code_score")), _fmt(r.get("held_out_score")),
                      _fmt(r.get("agent_score")), _fmt(r.get("math_score")),
                      _fmt(r.get("tok_per_s"), "{:.0f}"),
                      f"{run.get('vram_gb', '?')} GB", (run.get("trust_tier") or "").replace("-", " "))
        self._note(f"{len(runs)} run(s). Same suite across quants = comparable (score vs tps vs VRAM)."
                   if runs else "No runs for this family yet.")

    def _note(self, msg: str) -> None:
        self.query_one("#q-note", Static).update(msg)


class LevelScreen(ModalScreen):
    """Pick a test level for a model with a time/data estimate, then run it. Estimates account for
    generation (tokens/tps), test execution, and download (prebuilt image bytes / measured bandwidth)."""
    CSS = """
    LevelScreen { align: center middle; }
    #levels { width: 96; height: 24; border: thick $accent; background: $surface; padding: 1; }
    #lvl-tbl { height: 1fr; }
    #lvl-note { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("r", "run", "Run"), ("enter", "run", "Run")]

    def __init__(self, model: str, base_url: str):
        super().__init__()
        self.model = model
        self.base_url = base_url

    def compose(self) -> ComposeResult:
        with Vertical(id="levels"):
            yield Static(f"[b]Levels[/b] for {self.model}  ·  ⏎/r run  ·  Esc close")
            yield DataTable(id="lvl-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("estimating…", id="lvl-note")

    def on_mount(self) -> None:
        self.query_one("#lvl-tbl", DataTable).add_columns(
            "Level", "Budget", "Challenges", "~Time", "~GB", "Flags")
        self.estimate_levels()

    @work(thread=True, exclusive=True)
    def estimate_levels(self) -> None:
        version, lvls = eng_levels.load_levels()
        rows = []
        for name, lv in lvls.items():
            try:
                e = eng_estimate.estimate(name, self.model)
            except Exception:  # noqa: BLE001
                e = None
            rows.append((name, lv, e))
        self.app.call_from_thread(self._fill, rows, version)

    def _fill(self, rows, version) -> None:
        t = self.query_one("#lvl-tbl", DataTable)
        t.clear()
        for name, lv, e in rows:
            if e:
                mins = e["total_min"]
                tm = f"{mins/60:.1f}h" if mins >= 90 else f"{mins:.0f}m"
                gb = f"{e['download_gb']:.0f}" if e["download_gb"] else "—"
                n = str(e["n_challenges"])
            else:
                tm = gb = n = "?"
            flags = "".join(c for c, on in [("J", lv.judge), ("A", lv.agent), ("P", lv.prebuilt)] if on) or "-"
            t.add_row(name, lv.time_hint, n, tm, gb, flags)
        self.query_one("#lvl-note", Static).update(
            f"manifest {version}  ·  estimates are rough (tps from last run, bandwidth from past "
            f"downloads).  ⏎ runs the selected level on {self.model}.")

    def _selected(self) -> str | None:
        t = self.query_one("#lvl-tbl", DataTable)
        if t.row_count == 0 or t.cursor_row is None:
            return None
        return str(t.get_row_at(t.cursor_row)[0])

    def action_run(self) -> None:
        name = self._selected()
        if name:
            self.dismiss()
            run_with_preflight(self, self.model, level=name)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="peakstone", description="Peakstone hardware dashboard")
    ap.add_argument("--api", default=client.API_DEFAULT, help="Peakstone API base URL")
    args = ap.parse_args()
    Dashboard(args.api).run()


if __name__ == "__main__":
    main()

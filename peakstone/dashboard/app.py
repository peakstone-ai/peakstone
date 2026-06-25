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
from . import client, hardware, history, models, reproduce

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
                          f"⏎ reproduce  c peakstones  m models{sel}")
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
                 challenge_ids: list[str] | None = None, level: str | None = None):
        super().__init__()
        self.model = model
        self.published_tps = published_tps
        self.base_url = base_url
        self.level = level
        self.challenge_ids = challenge_ids or REPRODUCE_IDS
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


class ModelsScreen(ModalScreen):
    CSS = """
    ModelsScreen { align: center middle; }
    #models { width: 90; height: 24; border: thick $accent; background: $surface; padding: 1; }
    #models-tbl { height: 1fr; }
    #dl-bar { margin-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("a", "add", "Add"),
                ("d", "download", "Download"), ("l", "levels", "Levels"), ("r", "run", "Run")]

    def compose(self) -> ComposeResult:
        with Vertical(id="models"):
            yield Static("[b]Local models[/b] (serve/models.toml)  ·  l levels  ·  r run  ·  "
                         "a add  ·  d download  ·  Esc close")
            yield DataTable(id="models-tbl", cursor_type="row", zebra_stripes=True)
            yield ProgressBar(id="dl-bar", show_eta=False)

    def on_mount(self) -> None:
        self.query_one("#models-tbl", DataTable).add_columns(
            "Model", "Present", "Size", "Fit", "TPS", "Caps", "Port")
        self.query_one("#dl-bar", ProgressBar).display = False
        self.refresh_models()

    def refresh_models(self) -> None:
        t = self.query_one("#models-tbl", DataTable)
        t.clear()
        max_vram = hardware.snapshot().max_vram_gb
        hist = history.load()

        def last_tps(name):
            for h in reversed(hist):
                if h.get("model") == name and h.get("your_tps"):
                    return h["your_tps"]
            return None

        for e in models.load_registry().values():
            fit = "?" if not e.size_gb else ("✓" if (max_vram and e.size_gb <= max_vram) else "✗")
            tps = last_tps(e.name)
            caps = eng_caps.effective_capabilities(e.name)
            caps_s = "".join(c for c, on in [("T", "tools" in caps), ("A", "agentic" in caps),
                                             ("R", "reasoner" in caps)] if on) or "-"
            t.add_row(e.name, "✓" if e.present else "—", f"{e.size_gb} GB" if e.size_gb else "—",
                      fit, _fmt(tps, "{:.0f}"), caps_s, str(e.port or ""))

    def action_add(self) -> None:
        self.app.push_screen(AddModelScreen(), lambda _ok: self.refresh_models())

    def _selected(self) -> str | None:
        t = self.query_one("#models-tbl", DataTable)
        if t.row_count == 0 or t.cursor_row is None:
            return None
        return str(t.get_row_at(t.cursor_row)[0])

    def action_download(self) -> None:
        name = self._selected()
        if name:
            self.download_model(name)

    def action_run(self) -> None:
        """Benchmark the selected model locally (download if needed) → a real, submittable run. No
        published baseline since this isn't a leaderboard row; press `s` in the run view to submit."""
        name = self._selected()
        if name:
            self.app.push_screen(ReproduceScreen(name, None, self.app.base_url,
                                                 challenge_ids=self.app.run_ids()))

    def action_levels(self) -> None:
        name = self._selected()
        if name:
            self.app.push_screen(LevelScreen(name, self.app.base_url))

    @work(thread=True, exclusive=True)
    def download_model(self, name: str) -> None:
        entry = models.load_registry().get(name)
        if entry:
            self.app.call_from_thread(self.app.notify, f"downloading {name}…")
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
                ("c", "clear", "Clear"), ("r", "run", "Run")]

    def __init__(self):
        super().__init__()
        self.sel = ch_browse.Selection()
        self._all_ids: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="challenges"):
            yield Static("[b]Peakstones[/b]  ·  ⏎ select  ·  space expand  ·  a all  ·  c clear  ·  r run  ·  Esc close")
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
        self._all_ids = [c.id for c in corpus]
        root = tree.root
        root.data = {"ids": self._all_ids, "base": f"All peakstones ({len(corpus)})", "kind": "root"}
        for family, chs in ch_browse.group_by_family(corpus).items():
            fam = root.add("", data={"ids": [c.id for c in chs], "base": f"{family} ({len(chs)})"})
            for bucket, dchs in ch_browse.group_by_date(chs).items():
                fam.add("", data={"ids": [c.id for c in dchs], "base": f"{bucket} ({len(dchs)})",
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

    def _refresh(self) -> None:
        tree = self.query_one("#ch-tree", Tree)
        for node in self._walk(tree.root):
            if node.data:
                node.set_label(f"{ch_browse.MARKER[self.sel.state(node.data['ids'])]} {node.data['base']}")
        n, total = len(self.sel.ids), len(self._all_ids)
        self.query_one("#ch-status", Static).update(
            f"[b]{n}[/] / {total} selected" + ("  ·  press [b]r[/] to run" if n else ""))

    def on_tree_node_selected(self, ev: "Tree.NodeSelected") -> None:
        if ev.node.data:                       # ⏎ on any node toggles its whole id-set
            self.sel.toggle(ev.node.data["ids"])
            self._refresh()

    def action_all(self) -> None:
        self.sel.ids = set(self._all_ids)
        self._refresh()

    def action_clear(self) -> None:
        self.sel.ids = set()
        self._refresh()

    def action_run(self) -> None:
        ids = self.sel.resolve()
        if not ids:
            self.notify("select at least one peakstone (space), or press a for all")
            return
        self.app.selected_ids = ids
        self.notify(f"{len(ids)} peakstones selected — pick a model to run")
        self.dismiss()
        self.app.push_screen(ModelsScreen())


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
            self.app.push_screen(ReproduceScreen(self.model, None, self.base_url, level=name))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="peakstone", description="Peakstone hardware dashboard")
    ap.add_argument("--api", default=client.API_DEFAULT, help="Peakstone API base URL")
    args = ap.parse_args()
    Dashboard(args.api).run()


if __name__ == "__main__":
    main()

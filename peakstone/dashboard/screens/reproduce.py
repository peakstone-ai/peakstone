"""The reproduce screen: run the pinned reproduce set against a model and watch it live."""
from __future__ import annotations

import time

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static
from rich.markup import escape
from rich.text import Text

from .. import client, models, reproduce
from ..ui import (GEN_ATTEMPT, GEN_MARK, GEN_NL, GEN_PHASE, REPRODUCE_IDS, HardwarePanel, _bar,
                  _ctx_k, _fmt, _model_says, _parse_result, _think_label)

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


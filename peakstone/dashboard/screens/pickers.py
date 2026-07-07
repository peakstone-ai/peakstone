"""Small modal pickers: a yes/no confirm and the run-launch settings (ctx / thinking / budget)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from .. import hardware, preflight
from ..ui import CTX_CHOICES, _ctx_k

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


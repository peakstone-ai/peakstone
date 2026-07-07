"""The preflight gate: VRAM/ctx fit-check a model, then hand off to the requested run."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from .. import models, preflight
from .reproduce import ReproduceScreen

class PreflightScreen(ModalScreen):
    """Shown before queueing when free accelerator memory looks too small for the model.
    INFORMATIONAL ONLY (review R21): the old 'free & run' lever SIGKILLed processes by pgrep —
    which would have killed the daemon's own llama-server — and was wired to a parameter nothing
    read. The daemon owns serving and swaps/unloads models itself; if it's wedged, `d` on the
    queue screen restarts it."""
    CSS = """
    PreflightScreen { align: center middle; }
    #preflight { width: 76; height: auto; border: thick $warning; background: $surface; padding: 1; }
    """

    def __init__(self, model_name: str, pf: "preflight.Preflight", on_proceed):
        super().__init__()
        self.model_name = model_name
        self.pf = pf
        self._on_proceed = on_proceed   # zero-arg: queue the run

    def compose(self) -> ComposeResult:
        pf = self.pf
        lines = ["[b yellow]Memory looks tight[/]",
                 f"{self.model_name} needs ~[b]{pf.need_gb}[/] GB · [b]{pf.free_gb}[/] GB free"]
        if pf.freeable:
            lines.append(f"\n{len(pf.freeable)} llama-server process(es) holding {pf.freeable_gb} GB:")
            lines += [f"  · pid {p.pid} ({p.name})  {p.used_gb} GB" for p in pf.freeable]
            lines.append("→ the daemon swaps its own model out when the run starts; if one of "
                         "these is wedged, restart the daemon ([b]d[/] on the queue screen).")
        else:
            lines.append("\nNo llama-servers of ours are holding memory — close other GPU apps, or:")
        lines.append("\n[b]r[/] run anyway   ·   [b]Esc[/] cancel")
        with Vertical(id="preflight"):
            yield Static("\n".join(lines))

    BINDINGS = [("escape", "cancel", "Cancel"), ("r", "run_anyway", "Run anyway")]

    def action_run_anyway(self) -> None:
        self.dismiss()
        self._on_proceed()

    def action_cancel(self) -> None:
        self.dismiss()


def run_with_preflight(screen, name: str, *, challenge_ids=None, level=None, published_tps=None) -> None:
    """Queue a reproduce run, first checking free accelerator memory. If a model won't fit, prompt to
    free our llama-servers (or run anyway) before queuing; a fresh run opens the live view, a run
    started while one is active is queued behind it."""
    app = screen.app
    entry = models.load_registry().get(name)
    pf = preflight.check(entry) if entry else None

    def launch() -> None:
        started = app.start_run(name, published_tps=published_tps, challenge_ids=challenge_ids,
                                level=level, ctx=app.ctx_for(name),
                                reasoning=app.reasoning_for(name), budget=app.budget_for(name))
        if started:
            app.push_screen(ReproduceScreen())

    # The preflight VRAM check only matters when the run starts NOW. If a run is already active this
    # one is QUEUED, and the active model stops (freeing its VRAM) before it starts — so don't warn.
    if pf and not pf.fits_now and not app.run_active:
        app.push_screen(PreflightScreen(name, pf, on_proceed=launch))
    else:
        launch()


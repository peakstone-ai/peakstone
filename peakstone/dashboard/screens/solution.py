"""The solution explorer: a challenge and the model's stored response, side by side."""
from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from .. import client
from ..ui import HardwarePanel

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


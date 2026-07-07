"""Shared dashboard UI vocabulary — split out of app.py (review R21).

The formatting helpers, nav-tree widgets, live hardware panel, and run-log progress rendering
that every screen (and the app shell) draws with. Pure presentation: nothing here talks to the
gateway or owns screen logic.
"""
from __future__ import annotations

import re
import time

from textual.binding import Binding
from textual.widgets import Static, Tree
from rich.console import Group
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from . import hardware, models

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


# Live-generation stream protocol — the ONE shared declaration (engine/streamproto.py, review
# R21): this file used to carry a hand-duplicated copy that could silently drift from the runner.
from peakstone.engine.streamproto import GEN_ATTEMPT, GEN_MARK, GEN_NL, GEN_PHASE  # noqa: E402
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


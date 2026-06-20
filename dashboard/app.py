"""Peakstone dashboard (Textual TUI) — live local hardware + a leaderboard browser auto-filtered to
what fits your GPU, so you can see how models that run on YOUR hardware compare (and at what TPS).

Run:  peakstone            (or)  python -m dashboard  [--api URL]
"""
from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from . import client, hardware


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
            lines.append("[yellow]No NVIDIA GPU detected — CPU only[/yellow]")
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
    ]
    SORTS = ["code_score", "agent_score", "planner_score", "tok_per_s"]

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.fit = True          # filter to models that fit my VRAM
        self.sort_i = 0

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
        self.sub_title = f"{self.base_url}  ·  {scope}  ·  sort: {self.SORTS[self.sort_i]}"
        rows = data.get("leaderboard", [])
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


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="peakstone", description="Peakstone hardware dashboard")
    ap.add_argument("--api", default=client.API_DEFAULT, help="Peakstone API base URL")
    args = ap.parse_args()
    Dashboard(args.api).run()


if __name__ == "__main__":
    main()

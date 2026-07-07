"""The wishlist screens: models to benchmark later, and adding to that list."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from .. import wishlist
from .models import QuantScreen

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


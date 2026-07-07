"""The self-update screen: check for a newer peakstone client and apply it."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

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


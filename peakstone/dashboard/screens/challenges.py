"""The challenge browser: the corpus as a tree, level membership, and run-from-selection."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, Tree

from peakstone.engine import levels as eng_levels

from .. import challenges as ch_browse
from ..ui import NavTree
from .models import ModelsScreen

class ChallengesScreen(ModalScreen):
    """Browse challenges by family → month → challenge and pick a set to run. Selecting everything
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
            yield Static("[b]Challenges[/b]  ·  [b]1-5[/] level (smoke→max)  ·  space select  ·  ⏎/→ expand  ·  ← collapse  "
                         "·  a all  ·  c clear  ·  r run  ·  Esc close")
            yield NavTree("challenges", id="ch-tree")
            yield Static("", id="ch-status")

    def on_mount(self) -> None:
        tree = self.query_one("#ch-tree", NavTree)
        tree.auto_expand = False   # selection (space) never auto-expands; ⏎/→ expand, ← collapse
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
        root.data = {"ids": self._all_ids, "base": f"All challenges ({len(corpus)})", "kind": "root"}
        for grp in ch_browse.group_by_collection(corpus):
            chs = grp["chs"]
            ids = [c.id for c in chs]
            if grp["kind"] == "native":   # our challenges: collection -> date -> language/axis family -> challenges
                node = root.add("", data={"ids": ids, "base": f"{grp['label']} ({len(chs)})", "kind": "native"})
                for bucket, dchs in ch_browse.group_by_date(chs).items():
                    dnode = node.add("", data={"ids": [c.id for c in dchs], "base": f"{bucket} ({len(dchs)})"})
                    for family, fchs in ch_browse.group_by_family(dchs).items():
                        dnode.add("", data={"ids": [c.id for c in fchs], "base": f"{family} ({len(fchs)})",
                                            "chs": fchs, "filled": False})
            else:                          # imported suite: suite -> month -> challenges
                node = root.add("", data={"ids": ids, "base": f"{grp['label']} ({len(chs)})", "kind": "suite"})
                for bucket, dchs in ch_browse.group_by_date(chs).items():
                    node.add("", data={"ids": [c.id for c in dchs], "base": f"{bucket} ({len(dchs)})",
                                       "chs": dchs, "filled": False})
        root.expand()
        self._refresh()
        # open ready-to-run on the official 'standard' level (press 1/2/4/5 or edit to change)
        if "standard" in self._level_names:
            self.action_select_level(self._level_names.index("standard"))

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
            self.notify(f"{name}: no matching challenges in the current corpus")
            return
        self.sel.ids = set(ids)
        self._chosen_level = name
        self._refresh()
        tags = self._level_tags(self._levels[name])
        self.notify(f"{name}: {len(ids)} challenges" + (f" · {tags}" if tags else "") + " — press r to run")

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
            self.notify("select at least one challenge (1-5 for a level, space to pick, or a for all)")
            return
        self.app.selected_ids = ids
        self.app.selected_level = self._chosen_level   # level run (settings apply) vs plain id run
        scope = f"level {self._chosen_level}" if self._chosen_level else f"{len(ids)} challenges"
        self.notify(f"{scope} selected — pick a model to run")
        self.dismiss()
        self.app.push_screen(ModelsScreen())


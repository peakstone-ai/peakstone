"""The model manager screens: browse/download/serve/run models, plus per-quant history."""
from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static, Tree

from peakstone.engine import capabilities as eng_caps

from .. import client, hardware, history, models
from ..ui import ModelTree, _ctx_k, _fmt, _think_label
from .pickers import BudgetScreen, ConfirmScreen, CtxScreen, ReasoningScreen
from .preflight import run_with_preflight
from .queue import QueueScreen

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
    """Pick a model to run the selected challenges on. Models are grouped as family → quant: the
    registry (serve/models.toml) provides the runnable/present quants; expanding a family lists the
    other quants its HF repo offers (downloadable). The header shows how many challenges will run."""
    CSS = """
    ModelsScreen { align: center middle; }
    #models { width: 92; height: 26; border: thick $accent; background: $surface; padding: 1; }
    #models-tree { height: 1fr; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("a", "add", "Add"),
                ("r", "run", "Run"), ("k", "ctx", "Context"),
                ("t", "reasoning", "Think"), ("b", "budget", "Budget"), ("v", "quants", "Quants"),
                ("u", "queue", "Queue"), ("U", "unload", "Unload VRAM"), ("x", "delete", "Delete")]

    def _header(self) -> str:
        ids, lvl = self.app.run_ids(), self.app.selected_level
        scope = f"level [b]{lvl}[/]" if lvl else f"[b]{len(ids)}[/] challenges"
        e = self._target_entry()
        cur = self.app.ctx_for(e.name) if e else self.app.ctx_overrides.get("")
        who = e.name if e else "default"
        ctx = f"[b]{_ctx_k(cur)}[/] ({who})" if cur else f"[b]default[/] ({who})"
        rsn = self.app.reasoning_for(e.name) if e else self.app.reasoning_overrides.get("")
        think = f"  ·  think [b]{_think_label(rsn)}[/]" if rsn is not None else ""
        bdg = self.app.budget_for(e.name) if e else self.app.budget_overrides.get("")
        budget = f"  ·  budget [b]{_ctx_k(bdg)}[/]" if bdg else ""
        return (f"[b]Models[/b] — will run {scope} @ ctx {ctx}{think}{budget}  ·  ⏎ expand · download · run  "
                "·  r run · k ctx · t think · b budget · v quants · a add · x del · u queue · Esc")

    def compose(self) -> ComposeResult:
        with Vertical(id="models"):
            yield Static(self._header(), id="models-hdr")
            yield ModelTree("models", id="models-tree")

    def _refresh_header(self) -> None:
        self.query_one("#models-hdr", Static).update(self._header())

    def on_tree_node_highlighted(self, _ev) -> None:
        self._refresh_header()          # the ctx shown follows the model under the cursor

    def action_ctx(self) -> None:
        e = self._target_entry()
        key = e.name if e else ""
        self.app.push_screen(
            CtxScreen(e, key, self.app.ctx_overrides.get(key)),
            lambda _=None: self._refresh_header())

    def action_reasoning(self) -> None:
        e = self._target_entry()
        key = e.name if e else ""
        self.app.push_screen(
            ReasoningScreen(e, key, self.app.reasoning_overrides.get(key)),
            lambda _=None: self._refresh_header())

    def action_budget(self) -> None:
        e = self._target_entry()
        key = e.name if e else ""
        self.app.push_screen(
            BudgetScreen(e, key, self.app.budget_overrides.get(key)),
            lambda _=None: self._refresh_header())

    def on_mount(self) -> None:
        tree = self.query_one("#models-tree", Tree)
        tree.show_root = False
        tree.auto_expand = False
        self._leaderboard = None
        self.refresh_models()      # registry-only first (instant, offline-safe)
        self.load_remote()         # then merge in models the server has run on similar hardware
        tree.focus()

    def _last_tps(self, name: str):
        for h in reversed(history.load()):
            if h.get("model") == name and h.get("your_tps"):
                return h["your_tps"]
        return None

    def _best_local_tps(self, entries):
        vals = [t for e in entries if (t := self._last_tps(e.name))]
        return max(vals) if vals else None

    @staticmethod
    def _fitmark(size, max_vram) -> str:
        if not size:
            return "?"
        return "✓" if (max_vram and size <= max_vram) else "✗"

    def _merged_families(self, leaderboard) -> list[dict]:
        """Registry families merged with leaderboard families (models others ran on hardware that fits
        ours), each annotated with a claimed tps. Sorted by that tps so the fastest-on-similar-hardware
        models lead; remote-only families (not in the registry) are downloadable."""
        fams: dict[str, dict] = {}
        for fam, entries in models.group_by_family(models.load_registry()).items():
            fams[fam] = {"family": fam, "entries": entries, "remote": False,
                         "repo": next((e.repo for e in entries if e.repo), None),
                         "tps": self._best_local_tps(entries), "hw": None}
        for row in (leaderboard or {}).get("leaderboard", []):
            name = row.get("family")
            if not name:
                continue
            run = row.get("run", {})
            f = fams.get(name) or fams.setdefault(name, {"family": name, "entries": [], "remote": True,
                                                          "repo": None, "tps": None, "hw": None})
            tps = row.get("tok_per_s")
            if tps is not None and (f["tps"] is None or f["remote"]):   # prefer the server's claimed tps
                f["tps"], f["hw"] = tps, run.get("vram_gb")
            f["repo"] = f["repo"] or run.get("hf_repo")
        return sorted(fams.values(), key=lambda f: (f["tps"] is None, -(f["tps"] or 0), f["family"]))

    def _family_label(self, f: dict, n_hf: int | None = None) -> str:
        tps = f.get("tps")
        tps_s = (f" · [b]{tps:.0f}[/] tps" + (f"@{f['hw']:.0f}GB" if f.get("hw") else "")) if tps else ""
        if f["remote"] and not f["entries"]:
            tag = f"(remote · {n_hf} quants" + ")" if n_hf else "(remote · ⏎ to see quants)"
        else:
            extra = f", +{n_hf} on HF" if n_hf else ""
            tag = f"({len(f['entries'])} local{extra})"
        return f"[b]{f['family']}[/]{tps_s}  {tag}"

    def _registry_label(self, e, max_vram) -> str:
        present = "✓" if e.present else "·"
        size = f"{e.size_gb} GB" if e.size_gb else "—"
        tps = self._last_tps(e.name)
        caps = eng_caps.effective_capabilities(e.name)
        caps_s = "".join(c for c, on in [("T", "tools" in caps), ("A", "agentic" in caps),
                                         ("R", "reasoner" in caps)] if on) or "-"
        return (f"{present} {e.quant:13} {size:>8}  {self._fitmark(e.size_gb, max_vram)}fit  "
                f"{(f'{tps:.0f} tps' if tps else '—'):>8}  {caps_s}")

    def _hf_label(self, q, max_vram) -> str:
        sz = q.get("size_gb")
        size = f"~{sz} GB" if sz else "—"
        return f"· {q['quant']:13} {size:>8}  {self._fitmark(sz, max_vram)}fit  (download)"

    def refresh_models(self, leaderboard=None) -> None:
        tree = self.query_one("#models-tree", Tree)
        tree.clear()
        max_vram = hardware.snapshot().max_vram_gb
        for f in self._merged_families(leaderboard):
            entries = f["entries"]
            present = next((e for e in entries if e.present), None)
            node = tree.root.add(self._family_label(f),
                                 data={"kind": "family", "f": f, "family": f["family"], "repo": f["repo"],
                                       "entries": entries, "entry": present or (entries[0] if entries else None),
                                       "remote": f["remote"], "hf_done": False})
            for e in entries:
                node.add_leaf(self._registry_label(e, max_vram), data={"kind": "registry", "entry": e})
            # families start collapsed — expand (⏎ or →) to see quants; HF discovery runs on expand
        if tree.root.children:
            tree.cursor_line = 0

    @work(thread=True, exclusive=True)
    def load_remote(self) -> None:
        try:
            lb = client.get_leaderboard(self.app.base_url, max_vram_gb=hardware.snapshot().max_vram_gb,
                                        sort="tok_per_s")
        except Exception:  # noqa: BLE001 — offline / no server: stay registry-only
            return
        self._leaderboard = lb
        n = lb.get("count", 0)
        self.app.call_from_thread(self.refresh_models, lb)
        if n:
            self.app.call_from_thread(self.app.notify,
                                      f"{n} model(s) with runs on hardware ≤ yours, sorted by tps")

    def on_tree_node_expanded(self, ev: "Tree.NodeExpanded") -> None:
        d = ev.node.data or {}
        if d.get("kind") == "family" and d.get("repo") and not d.get("hf_done"):
            d["hf_done"] = True   # set now so a quick re-expand doesn't double-fetch
            self.discover_hf(ev.node)

    @work(thread=True)
    def discover_hf(self, node) -> None:
        d = node.data or {}
        quants = models.available_quants(d["repo"])
        have = {e.quant for e in d["entries"]}
        extra = [q for q in quants if q["quant"] not in have]
        if extra:
            self.app.call_from_thread(self._add_hf, node, extra)

    def _add_hf(self, node, extra) -> None:
        max_vram = hardware.snapshot().max_vram_gb
        d = node.data
        for q in extra:
            node.add_leaf(self._hf_label(q, max_vram),
                          data={"kind": "hf", "family": d["family"], "repo": d["repo"],
                                "file": q["file"], "quant": q["quant"], "size_gb": q.get("size_gb")})
        node.set_label(self._family_label(d["f"], len(extra)))

    def _node_data(self) -> dict:
        try:                                   # the header reads this during compose, before the tree mounts
            n = self.query_one("#models-tree", Tree).cursor_node
        except Exception:  # noqa: BLE001
            return {}
        return (n.data if n else None) or {}

    def _target_entry(self):
        """The registry entry to act on: a quant leaf's entry, or a family's present/first quant."""
        d = self._node_data()
        return d.get("entry") if d.get("kind") in ("registry", "family") else None

    def action_delete(self) -> None:
        """Delete the highlighted model's downloaded GGUF from disk (confirmed)."""
        e = self._target_entry()
        if not (e and e.present):
            self.notify("no downloaded model under the cursor to delete")
            return
        size = f" · {e.size_gb} GB" if e.size_gb else ""

        def do_delete() -> None:
            if models.delete_model(e):
                self.notify(f"deleted {e.name} {e.quant}{size}")
                self.refresh_models()
            else:
                self.notify("delete failed", severity="error")

        self.app.push_screen(ConfirmScreen(
            f"Delete [b]{e.name}[/] {e.quant}{size} from disk?\n"
            "The GGUF file is removed (re-download anytime); the registry entry stays.",
            do_delete))

    def action_queue(self) -> None:
        self.app.push_screen(QueueScreen())

    @work(thread=True, exclusive=True, group="unload")
    def action_unload(self) -> None:
        """Free VRAM by unloading the gateway's currently-loaded model (refused while a run holds it).
        Off-thread because stopping llama-server can take a moment; the hardware panel updates itself."""
        try:
            ok, detail = client.unload_model()
        except client.APIError as e:   # daemon unreachable — notify, don't let the worker crash the app
            ok, detail = False, f"unload failed: {e}"
        self.app.call_from_thread(self.notify, detail, severity="information" if ok else "warning")

    def action_quants(self) -> None:
        d = self._node_data()
        if d.get("kind") == "registry":
            e = d["entry"]
            fam, repo = e.fam, e.repo
        else:
            fam, repo = d.get("family"), d.get("repo")
        if fam:
            self.app.push_screen(QuantScreen(fam, self.app.base_url, repo=repo))

    def action_run(self) -> None:
        """Run the selected quant (download first if needed) — a real, submittable run."""
        e = self._target_entry()
        if not e:
            self.notify("pick a registered quant — ⏎ an HF quant to download + run it")
            return
        run_with_preflight(self, e.name, challenge_ids=self.app.run_ids(), level=self.app.selected_level)

    def action_enter(self) -> None:
        """⏎ on a quant: run it if it's downloaded; otherwise confirm, then queue a download+run job."""
        d = self._node_data()
        if d.get("kind") == "registry":
            e = d["entry"]
            if e.present:
                self._run(e.name)
            else:
                self._confirm_download_run(e.quant, name=e.name)
        elif d.get("kind") == "hf":
            self._confirm_download_run(d["quant"], register=(d["family"], d["repo"], d["file"], d["quant"]))

    def _run(self, name: str) -> None:
        run_with_preflight(self, name, challenge_ids=self.app.run_ids(), level=self.app.selected_level)

    def _confirm_download_run(self, label: str, *, name: str | None = None, register=None) -> None:
        def go() -> None:
            nm = name
            if register is not None:                 # HF-only quant: register it so it can be served
                try:
                    nm = models.register_quant(*register).name
                except Exception as ex:  # noqa: BLE001
                    self.notify(f"register failed: {ex}")
                    return
            self._run(nm)                            # reproduce downloads (as part of the queued job) then runs
        self.app.push_screen(ConfirmScreen(
            f"[b]{label}[/] isn't downloaded. Download and run it?\nThe download runs as a queued job.", go))


class QuantScreen(ModalScreen):
    """Compare a model family's quants side by side: every quant it has — downloaded (✓), registered,
    or just available on HF (·) — with leaderboard scores where someone has run it. Download the
    highlighted quant with `d`. Merges the local registry, the HF repo listing, and the API."""
    CSS = """
    QuantScreen { align: center middle; }
    #quants { width: 104; height: 24; border: thick $accent; background: $surface; padding: 1; }
    #q-tbl { height: 1fr; }
    #q-note { height: auto; padding-top: 1; }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("d", "download", "Download")]

    def __init__(self, family: str, base_url: str, repo: str | None = None):
        super().__init__()
        self.family = family
        self.base_url = base_url
        self.repo = repo
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="quants"):
            yield Static(f"[b]Quants[/b] for {self.family}  ·  d download  ·  Esc close")
            yield DataTable(id="q-tbl", cursor_type="row", zebra_stripes=True)
            yield Static("loading…", id="q-note")

    def on_mount(self) -> None:
        self.query_one("#q-tbl", DataTable).add_columns(
            "Quant", "State", "Size", "Code", "Held-out", "Agent", "Math", "TPS", "Trust")
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        reg = {e.quant: e for e in models.load_registry().values() if e.fam == self.family}
        repo = self.repo or next((e.repo for e in reg.values() if e.repo), None)
        hf = {h["quant"]: h for h in (models.available_quants(repo) if repo else [])}
        try:
            runs = client.get_model(self.base_url, self.family).get("runs", [])
        except client.APIError:
            runs = []
        run_by_q: dict[str, dict] = {}
        for r in runs:                                   # keep the best code score per quant
            q = r.get("run", {}).get("artifact", "?")
            if q not in run_by_q or (r.get("code_score") or 0) > (run_by_q[q].get("code_score") or 0):
                run_by_q[q] = r
        rows = []
        for q in sorted(set(reg) | set(hf) | set(run_by_q)):
            e, h, run = reg.get(q), hf.get(q), run_by_q.get(q)
            present = bool(e and e.present)
            rinfo = (run or {}).get("run", {})
            rows.append({
                "quant": q,
                "state": "✓ local" if present else ("· registered" if e else "· HF"),
                "size": (f"{e.size_gb} GB" if (e and e.size_gb)
                         else f"~{h['size_gb']} GB" if (h and h.get("size_gb")) else "—"),
                "code": (run or {}).get("code_score"), "held": (run or {}).get("held_out_score"),
                "agent": (run or {}).get("agent_score"), "math": (run or {}).get("math_score"),
                "tps": (run or {}).get("tok_per_s"), "trust": (rinfo.get("trust_tier") or "").replace("-", " "),
                "present": present, "entry": e, "repo": repo, "file": h["file"] if h else None})
        self.app.call_from_thread(self._fill, rows)

    def _fill(self, rows) -> None:
        t = self.query_one("#q-tbl", DataTable)
        t.clear()
        self._rows = rows
        for r in rows:
            t.add_row(r["quant"], r["state"], r["size"], _fmt(r["code"]), _fmt(r["held"]),
                      _fmt(r["agent"]), _fmt(r["math"]), _fmt(r["tps"], "{:.0f}"), r["trust"])
        scored = sum(1 for r in rows if r["code"] is not None)
        self.query_one("#q-note", Static).update(
            f"{len(rows)} quant(s) · {scored} with leaderboard runs · ✓ local · · downloadable (d)"
            if rows else "no quants found (registry / HF / leaderboard all empty)")

    def action_download(self) -> None:
        t = self.query_one("#q-tbl", DataTable)
        if t.cursor_row is None or t.cursor_row >= len(self._rows):
            return
        row = self._rows[t.cursor_row]
        if row["present"]:
            self.notify(f"{row['quant']} already downloaded")
            return
        entry = row["entry"]
        if entry is None:                        # HF-only quant: register it so it can be served
            if not (row["repo"] and row["file"]):
                self.notify("no HF source for this quant")
                return
            try:
                entry = models.register_quant(self.family, row["repo"], row["file"], row["quant"])
            except Exception as ex:  # noqa: BLE001
                self.notify(f"register failed: {ex}")
                return
        started = self.app.start_download(entry.name)   # download runs on the daemon's download queue
        if started:
            self.notify(f"queued download: {entry.name} — open the queue (u) to watch it")
        self.app.call_from_thread(self.load)


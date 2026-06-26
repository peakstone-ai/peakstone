"""Dashboard tests — hardware detection + a headless Textual run with a stubbed API."""
from __future__ import annotations

import asyncio

import pytest
from textual.widgets import DataTable, Static

from peakstone.dashboard import client, hardware
from peakstone.dashboard import models as _models
from peakstone.dashboard.app import Dashboard, _bar, _fmt

# Captured before any stubbing so the cache-path test can call the real implementation.
_REAL_AVAILABLE_QUANTS = _models.available_quants


@pytest.fixture(autouse=True)
def _no_hf_network(monkeypatch):
    """The models screen auto-expands families, which kicks off HF quant discovery in worker threads;
    keep that off the network in tests (a real lookup would block worker shutdown at app exit)."""
    monkeypatch.setattr(_models, "available_quants", lambda repo, **k: [])

_FAKE = {"count": 2, "leaderboard": [
    {"rank": 1, "family": "qwen3-coder", "code_score": 0.93, "agent_score": None,
     "planner_score": None, "tok_per_s": 85.0, "sol_per_s": 0.5, "n_total": 50,
     "run": {"vram_gb": 24, "ram_gb": 64, "vram_used_gb": 24, "ram_used_gb": 26,
             "trust_tier": "community-verified"}},                       # spilled to RAM
    {"rank": 2, "family": "phi-4-mini", "code_score": 0.42, "agent_score": None,
     "planner_score": None, "tok_per_s": 120.0, "sol_per_s": 1.2, "n_total": 12,
     "run": {"vram_gb": 8, "ram_gb": 32, "vram_used_gb": 3.2, "ram_used_gb": 0.5,
             "trust_tier": "self-reported"}},
]}


def test_hardware_snapshot():
    s = hardware.snapshot()
    assert s.cores > 0 and s.ram_total_mib > 0
    assert isinstance(s.max_vram_gb, float)
    # GPUs (if any) parse into structured records
    for g in s.gpus:
        assert g.mem_total_mib > 0 and g.vram_gb > 0


def test_helpers():
    assert _bar(2, 4).startswith("[") and "2/4" in _bar(2, 4)
    assert _bar(0, 0).endswith("0/0")          # no div-by-zero
    assert _fmt(0.126) == "0.13" and _fmt(None) == "—" and _fmt(85.0, "{:.0f}") == "85"
    from peakstone.dashboard.app import _mem
    assert _mem(24, 26) == "24/26 GB" and _mem(24, None) == "24 GB" and _mem(None, None) == "?"


def test_app_renders_filtered_leaderboard(monkeypatch):
    captured = {}

    def fake_get(base_url, *, max_vram_gb=None, sort="code_score", timeout=10):
        captured["max_vram_gb"] = max_vram_gb
        captured["sort"] = sort
        return _FAKE

    monkeypatch.setattr(client, "get_leaderboard", fake_get)

    async def scenario():
        app = Dashboard("http://test")
        async with app.run_test() as pilot:
            app._corpus_total = 1965                             # fixed denominator for the assertion
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one(DataTable)
            assert table.row_count == 2
            cols = [str(c.label) for c in table.columns.values()]
            assert cols == ["#", "Model", "Code", "Agentic", "Planner", "TPS", "sol/s",
                            "VRAM/RAM", "Trust", "Coverage"]
            assert str(table.get_row_at(0)[6]) == "0.50"        # sol/s after TPS
            assert str(table.get_row_at(0)[7]) == "24/26 GB"    # VRAM/RAM used (spilled to RAM)
            assert str(table.get_row_at(0)[9]) == "50/1965"     # coverage: run / total peakstones
            # fit filter on by default -> the request was scoped to local VRAM (or None if no GPU)
            assert "max_vram_gb" in captured
            # cycling sort re-queries with the next axis
            await pilot.press("s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert captured["sort"] == "held_out_score"   # SORTS: code_score -> held_out_score -> ...
            # toggling the fit filter off drops the VRAM scope
            await pilot.press("f")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert captured["max_vram_gb"] is None

    asyncio.run(scenario())


def test_registry_add_and_list(monkeypatch, tmp_path):
    from peakstone.dashboard import models
    toml = tmp_path / "serve" / "models.toml"
    toml.parent.mkdir()
    toml.write_text('["existing"]\nrepo="r"\nfile="models/existing/x.gguf"\nport=8081\nctx=32768\nflags=""\n')
    monkeypatch.setattr(models, "REPO", tmp_path)
    monkeypatch.setattr(models, "MODELS_TOML", toml)
    assert "existing" in models.load_registry()
    e = models.add_model("new-m", "org/repo", "File-Q4_K.gguf")
    assert e.port == 8082 and e.file == "models/new-m/File-Q4_K.gguf"
    assert "new-m" in models.load_registry()
    with pytest.raises(ValueError):
        models.add_model("new-m", "r")           # duplicate rejected
    with pytest.raises(ValueError):
        models.add_model("bad name!", "r")       # invalid name rejected


def test_download_invokes_hf_with_progress(monkeypatch, tmp_path):
    from peakstone.dashboard import models
    monkeypatch.setattr(models, "REPO", tmp_path)
    monkeypatch.setattr(models, "remote_size", lambda repo, fn: 1000)   # known total -> real bar
    monkeypatch.setattr(models.time, "sleep", lambda s: None)
    e = models.ModelEntry("m", "org/repo", "models/m/x.gguf", 8081, 32768, "")
    calls, progress = {}, []

    class FakeProc:
        returncode = 0

        def __init__(self):
            self._n = 0

        def poll(self):
            self._n += 1
            return None if self._n == 1 else 0   # one loop iteration, then done

    def fake_popen(cmd, **kw):
        calls["cmd"] = cmd
        return FakeProc()

    models.download(e, popen=fake_popen, progress=lambda d, t: progress.append((d, t)))
    assert calls["cmd"][:3] == ["hf", "download", "org/repo"] and "--local-dir" in calls["cmd"]
    assert progress and progress[-1][1] == 1000        # total reported to the progress bar


def test_submit_bundle(monkeypatch):
    from peakstone.dashboard import client

    class FakeResp:
        status = 201

        def read(self):
            return b'{"id": 1, "trust_tier": "self-reported"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(client.urllib.request, "urlopen", lambda req, timeout=30: FakeResp())
    status, detail = client.submit_bundle("http://x", {"bundle_version": "1"})
    assert status == 201 and "id" in detail


def test_history_append_load(monkeypatch, tmp_path):
    from peakstone.dashboard import history
    monkeypatch.setattr(history, "HOME", tmp_path)
    monkeypatch.setattr(history, "HISTORY_PATH", tmp_path / "h.json")
    assert history.load() == []
    history.append({"model": "m", "ok": True, "your_tps": 80})
    h = history.load()
    assert len(h) == 1 and h[0]["model"] == "m" and "at" in h[0]


def test_reproduce_orchestration(monkeypatch):
    from peakstone.dashboard import models, reproduce
    entry = models.ModelEntry("m", "org/repo", "models/m/x.gguf", 8099, 32768, "")  # not present
    monkeypatch.setattr(models, "load_registry", lambda: {"m": entry})
    bundle = {"results": [
        {"verification": "deterministic-tests", "tok_per_s": 80.0, "score": {"final": 1.0, "passed": 8, "total": 10}},
        {"verification": "deterministic-tests", "tok_per_s": 90.0, "score": {"final": 0.5, "passed": 5, "total": 10}},
    ]}
    res = reproduce.reproduce("m", challenge_ids=["a"], published_tps=100.0,
                              _download=lambda e, log, **k: True, _serve=lambda n: object(),
                              _wait=lambda p, **k: True, _bench=lambda n, ids, **k: bundle, _stop=lambda p: None)
    assert res.ok and res.your_tps == 85.0 and res.code_score == 0.75
    assert res.passed == 13 and res.total == 20 and res.tps_ratio == 0.85

    # failure paths return a structured result, never raise
    monkeypatch.setattr(models, "load_registry", lambda: {})
    assert reproduce.reproduce("ghost", challenge_ids=["a"]).ok is False
    monkeypatch.setattr(models, "load_registry", lambda: {"m": entry})
    unhealthy = reproduce.reproduce("m", challenge_ids=["a"], _download=lambda e, log, **k: True,
                                    _serve=lambda n: object(), _wait=lambda p, **k: False,
                                    _bench=lambda n, ids, **k: bundle, _stop=lambda p: None)
    assert unhealthy.ok is False and "healthy" in unhealthy.note

    # a crashed serve process (poll() returns an exit code) fails fast with the crash reason, not "healthy"
    class _Dead:
        def poll(self):
            return 1
    crashed = reproduce.reproduce("m", challenge_ids=["a"], _download=lambda e, log, **k: True,
                                  _serve=lambda n: _Dead(), _wait=lambda p, proc=None: False,
                                  _bench=lambda n, ids, **k: bundle, _stop=lambda p: None)
    assert crashed.ok is False and "exited before serving" in crashed.note


def test_reproduce_screen_shows_result_and_records_history(monkeypatch):
    from peakstone.dashboard import history
    from peakstone.dashboard import reproduce as R
    from peakstone.dashboard.app import Dashboard, ReproduceScreen
    monkeypatch.setattr(R, "reproduce", lambda model, **k: R.ReproduceResult(
        model, True, your_tps=80.0, published_tps=100.0, code_score=0.9, passed=9, total=10,
        note="done", bundle={"bundle_version": "1"}))
    recorded = []
    monkeypatch.setattr(history, "append", recorded.append)
    submitted = {}
    monkeypatch.setattr(R, "ReproduceResult", R.ReproduceResult)  # keep dataclass

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            app.start_run("qwen3-coder", published_tps=100.0)        # app-level run manager
            await app.workers.wait_for_complete()                    # run completes on the app worker
            await app.push_screen(ReproduceScreen())                 # viewer backfills the finished run
            await pilot.pause()
            result = str(app.screen.query_one("#repro-result", Static).render())
            assert "80" in result and "0.8" in result and "submit" in result
            # the run was recorded in history
            assert recorded and recorded[0]["model"] == "qwen3-coder" and recorded[0]["your_tps"] == 80.0
            # pressing 's' submits the bundle
            from peakstone.dashboard import client
            monkeypatch.setattr(client, "submit_bundle", lambda url, b, **k: submitted.update(b=b) or (201, "ok"))
            await pilot.press("s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert submitted.get("b") == {"bundle_version": "1"}

    asyncio.run(scenario())


def test_models_screen_run_opens_reproduce(monkeypatch):
    from peakstone.dashboard import history, models
    from peakstone.dashboard import reproduce as R
    from peakstone.dashboard.app import Dashboard, ModelsScreen, ReproduceScreen
    monkeypatch.setattr(R, "reproduce", lambda model, **k: R.ReproduceResult(model, True, your_tps=70.0, note="done"))
    monkeypatch.setattr(history, "append", lambda e: None)
    monkeypatch.setattr(models, "available_quants", lambda repo, **k: [])   # no HF network in tests
    monkeypatch.setattr("peakstone.dashboard.preflight.check", lambda e: None)   # skip GPU pre-flight

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(ModelsScreen())   # the real registry has models -> a selectable row
            await pilot.pause()
            await pilot.press("r")                   # r runs the selected model
            await pilot.pause()
            assert isinstance(app.screen, ReproduceScreen)
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(scenario())


def _fake_ch(cid, family, published_at=""):
    from pathlib import Path
    from peakstone.engine.challenges import Challenge
    return Challenge(id=cid, title=cid.upper(), language="python", difficulty=1,
                     category="code-correctness", scoring="tests", solution_file="solution.py",
                     timeout=30, dir=Path(f"challenges/{family}/{cid}"), spec="",
                     published_at=published_at)


_FAKE_CORPUS = [
    _fake_ch("he-000", "humaneval", "2021-07-07"),
    _fake_ch("lcb-a", "livecodebench", "2025-01-04"),
    _fake_ch("lcb-b", "livecodebench", "2025-03-22"),
    _fake_ch("py-1", "python", ""),
]


def test_challenge_grouping_and_selection():
    from peakstone.dashboard import challenges as cb
    fam = cb.group_by_family(_FAKE_CORPUS)
    assert list(fam) == ["livecodebench", "humaneval", "python"]   # largest family first
    dates = cb.group_by_date(_FAKE_CORPUS)
    assert list(dates) == ["2021-07", "2025-01", "2025-03", cb.UNDATED]  # chronological, undated last

    sel = cb.Selection()
    lcb_ids = ["lcb-a", "lcb-b"]
    assert sel.state(lcb_ids) == "none"
    sel.toggle(lcb_ids)                       # select the whole family
    assert sel.state(lcb_ids) == "all" and sel.resolve() == ["lcb-a", "lcb-b"]
    sel.toggle(["lcb-a"])                     # deselect one -> partial
    assert sel.state(lcb_ids) == "some" and sel.resolve() == ["lcb-b"]
    sel.toggle(lcb_ids)                       # not all present -> selects the whole group
    assert sel.state(lcb_ids) == "all"


def test_group_by_collection():
    from peakstone.dashboard import challenges as cb
    groups = cb.group_by_collection(_FAKE_CORPUS)
    kinds = [(g["kind"], g["label"], len(g["chs"])) for g in groups]
    # native first (our authored peakstones collapsed), then imported suites largest-first
    assert kinds == [("native", "Native", 1), ("suite", "livecodebench", 2), ("suite", "humaneval", 1)]
    native = next(g for g in groups if g["kind"] == "native")
    assert [c.id for c in native["chs"]] == ["py-1"]
    # a single-month native set captions with that month; mixed/undated handled by date_span
    assert cb.date_span([_fake_ch("a", "python", "2026-07-01")]) == "2026-07"
    assert cb.date_span(_FAKE_CORPUS) == "2021-07…2025-03"
    assert cb.date_span([_fake_ch("u", "python", "")]) == ""
    # rough at-a-glance ETA (1 solve/sec): empty when nothing selected, then s -> m -> h
    assert (cb.rough_eta(0), cb.rough_eta(4), cb.rough_eta(278), cb.rough_eta(1934)) == ("", "~4s", "~5m", "~32m")


def test_tree_nav_keys(monkeypatch):
    from peakstone.dashboard import challenges as cb
    from peakstone.dashboard.app import Dashboard, ChallengesScreen, NavTree
    monkeypatch.setattr(cb, "load_corpus", lambda: _FAKE_CORPUS)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.push_screen(ChallengesScreen())
            await pilot.pause()
            scr = app.screen
            tree = scr.query_one("#ch-tree", NavTree)
            await pilot.press("space")          # space = select (root -> selects all)
            await pilot.pause()
            assert scr.sel.ids                  # selection happened on space, not expand
            await pilot.press("down")           # to first collection node (collapsed)
            await pilot.pause()
            await pilot.press("right")          # right = expand
            await pilot.pause()
            assert tree.cursor_node.is_expanded
            await pilot.press("left")           # left = collapse
            await pilot.pause()
            assert not tree.cursor_node.is_expanded
            await pilot.press("enter")          # enter = toggle (expand)
            await pilot.pause()
            assert tree.cursor_node.is_expanded

    asyncio.run(scenario())


def test_challenges_screen_selects_and_runs(monkeypatch):
    from peakstone.dashboard import challenges as cb
    from peakstone.dashboard.app import Dashboard, ChallengesScreen, ModelsScreen
    monkeypatch.setattr(cb, "load_corpus", lambda: _FAKE_CORPUS)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(ChallengesScreen())
            await pilot.pause()
            await pilot.press("a")      # select all
            await pilot.pause()
            await pilot.press("r")      # run -> stash selection, open ModelsScreen
            await pilot.pause()
            assert app.selected_ids == ["he-000", "lcb-a", "lcb-b", "py-1"]
            assert isinstance(app.screen, ModelsScreen)

    asyncio.run(scenario())


def test_challenges_screen_level_shortcut(monkeypatch):
    from peakstone.dashboard import challenges as cb
    from peakstone.engine import levels as eng_levels
    from peakstone.dashboard.app import Dashboard, ChallengesScreen, ModelsScreen
    monkeypatch.setattr(cb, "load_corpus", lambda: _FAKE_CORPUS)
    _, lvls = eng_levels.load_levels()
    quick_ids = sorted(eng_levels.resolve(lvls["quick"], _FAKE_CORPUS))

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(ChallengesScreen())
            await pilot.pause()
            await pilot.press("2")      # quick level shortcut -> loads its bench selection
            await pilot.pause()
            scr = app.screen
            assert scr._chosen_level == "quick"
            assert sorted(scr.sel.ids) == quick_ids
            await pilot.press("r")      # run -> stash ids + level, open ModelsScreen
            await pilot.pause()
            assert app.selected_ids == quick_ids
            assert app.selected_level == "quick"     # carries level settings into the run
            assert isinstance(app.screen, ModelsScreen)

    asyncio.run(scenario())


def test_challenges_screen_manual_edit_clears_level(monkeypatch):
    from peakstone.dashboard import challenges as cb
    from peakstone.dashboard.app import Dashboard, ChallengesScreen
    monkeypatch.setattr(cb, "load_corpus", lambda: _FAKE_CORPUS)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(ChallengesScreen())
            await pilot.pause()
            await pilot.press("2")          # pick a level
            await pilot.pause()
            assert app.screen._chosen_level == "quick"
            await pilot.press("a")          # select-all is a manual edit -> custom selection
            await pilot.pause()
            assert app.screen._chosen_level is None
            await pilot.press("r")
            await pilot.pause()
            assert app.selected_level is None   # plain id run, not a level run

    asyncio.run(scenario())


def test_model_tree_enter_expands_then_confirms_download_run(monkeypatch):
    from peakstone.dashboard import models, history
    from peakstone.dashboard import reproduce as R
    from peakstone.dashboard.app import Dashboard, ModelsScreen, ConfirmScreen
    from textual.widgets import Tree
    entry = models.ModelEntry("m-q4", "org/r", "models/m/x-Q4_K_M.gguf", 8081, 32768, "", "fam")  # not present
    monkeypatch.setattr(models, "load_registry", lambda: {"m-q4": entry})
    monkeypatch.setattr(models, "available_quants", lambda repo, **k: [])
    monkeypatch.setattr("peakstone.dashboard.preflight.check", lambda e: None)
    monkeypatch.setattr(history, "append", lambda e: None)
    ran = []
    monkeypatch.setattr(R, "reproduce", lambda model, **k: ran.append(model) or R.ReproduceResult(model, True))

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.push_screen(ModelsScreen())
            await pilot.pause()
            t = app.screen.query_one("#models-tree", Tree)
            fam = t.root.children[0]
            assert not fam.is_expanded                 # families start collapsed
            await pilot.press("enter")                 # ⏎ on a family -> expand
            await pilot.pause()
            assert fam.is_expanded
            await pilot.press("down")                  # to the quant leaf (not downloaded)
            await pilot.press("enter")                 # ⏎ on a not-present quant -> confirm download+run
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            await pilot.press("y")                     # confirm -> queue a download+run job
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert ran == ["m-q4"]                     # the run executed (reproduce downloads first)

    asyncio.run(scenario())


def test_quant_label_and_grouping():
    from peakstone.dashboard import models
    assert models.quant_label("Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf") == "UD-Q4_K_XL"
    assert models.quant_label("Phi-4-mini-instruct-Q6_K.gguf") == "Q6_K"
    assert models.quant_label("vibethinker-3b-q8_0.gguf") == "Q8_0"
    assert models.quant_label("model.gguf") == "?"

    reg = {
        "a-q4": models.ModelEntry("a-q4", "org/A", "models/a/A-Q4_K_M.gguf", 8081, 32768, "", "fam-a"),
        "a-q6": models.ModelEntry("a-q6", "org/A", "models/a/A-Q6_K.gguf", 8082, 32768, "", "fam-a"),
        "b": models.ModelEntry("b", "org/B", "models/b/B-Q8_0.gguf", 8083, 32768, ""),  # family defaults to name
    }
    g = models.group_by_family(reg)
    assert list(g) == ["b", "fam-a"]                          # families alphabetical
    assert [e.quant for e in g["fam-a"]] == ["Q4_K_M", "Q6_K"]  # quants sorted within a family


def test_available_quants_uses_cache(tmp_path):
    import json
    from peakstone.dashboard import models
    cache = tmp_path / "hf.json"
    cache.write_text(json.dumps({"org/Repo": [{"quant": "Q6_K", "file": "x-Q6_K.gguf", "size_gb": 27.0}]}))
    assert _REAL_AVAILABLE_QUANTS("org/Repo", cache_path=cache) == \
        [{"quant": "Q6_K", "file": "x-Q6_K.gguf", "size_gb": 27.0}]   # cache hit, no network


def test_register_quant(tmp_path, monkeypatch):
    from peakstone.dashboard import models
    toml = tmp_path / "models.toml"
    toml.write_text('["base-q4"]\nrepo  = "org/R"\nfile  = "models/base/R-Q4_K_M.gguf"\nport  = 8081\nfamily = "base"\n')
    monkeypatch.setattr(models, "MODELS_TOML", toml)
    e = models.register_quant("base", "org/R", "R-Q6_K.gguf", "Q6_K")
    assert e.name == "base-q6_k" and e.family == "base"
    assert "base" in {x.fam for x in models.load_registry().values()}
    again = models.register_quant("base", "org/R", "models/base/R-Q4_K_M.gguf", "Q4_K_M")  # already registered
    assert again.name == "base-q4"


def test_reproduce_screen_routes_generation_stream():
    from peakstone.dashboard.app import Dashboard, ReproduceScreen, GEN_MARK, GEN_NL
    from textual.widgets import Static, RichLog

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            scr = ReproduceScreen()
            await app.push_screen(scr)
            await pilot.pause()
            scr._on_line("   m | py-05-calc          → solving [tests] …")   # progress -> log + sets challenge
            scr._on_line(GEN_MARK + "def f():" + GEN_NL + "  return 1")       # gen delta -> output panel
            scr._on_line(GEN_MARK + " more")
            await pilot.pause()
            gen = str(scr.query_one("#repro-gen", Static).render())
            assert "py-05-calc" in gen and "def f():\n  return 1 more" in gen
            log = str(scr.query_one("#repro-log", RichLog).lines)
            assert "py-05-calc" in log and GEN_MARK not in gen   # control char stripped from display

    asyncio.run(scenario())


def test_reproduce_screen_coverage_and_rate():
    from peakstone.dashboard.app import Dashboard, ReproduceScreen
    from textual.widgets import Static

    async def scenario():
        app = Dashboard("http://x")
        app._corpus_total = 1965                                              # fixed suite denominator
        async with app.run_test() as pilot:
            scr = ReproduceScreen()
            await app.push_screen(scr)
            await pilot.pause()
            scr._on_line("Running 1 model(s) over 3 challenge(s). judge=False")   # total parsed from here
            scr._on_line("   m | a   → solving [tests] …")
            scr._on_line("   m | a   ok  tests 10/10")                            # result -> 1 done
            scr._on_line("   m | b   → solving [tests] …")
            scr._on_line("   m | b   !! tests 3/10")                              # result -> 2 done
            await pilot.pause()
            stat = str(scr.query_one("#repro-stat", Static).render())
            assert "coverage 2/3" in stat and "3/1965 of suite" in stat and "sol/s" in stat

    asyncio.run(scenario())


def test_pretty_progress():
    from peakstone.dashboard.app import _pretty_progress
    assert "[green]✓[/]" in _pretty_progress("m | ch  ok  tests 10/10")
    assert "[red]✗[/]" in _pretty_progress("m | ch  !! refusal expect=refuse got=answered")
    assert "⟳" in _pretty_progress("m | ch  → solving [tests] …")
    assert "✗ ERROR" in _pretty_progress("m | ch  ERROR boom")


def test_bench_streams_progress(tmp_path):
    from peakstone.dashboard import reproduce as R
    (tmp_path / "bundle.json").write_text('{"results": []}')
    out_lines, fed = [], ["m | ch1  → solving [tests] …\n", "m | ch1  ok  tests 10/10\n"]

    class FakeProc:
        pid = 4321

        def __init__(self):
            self.stdout = iter(fed)

        def wait(self):
            return 0

    def fake_popen(cmd, **kw):
        assert "-u" in cmd and kw.get("env", {}).get("PYTHONUNBUFFERED") == "1"   # unbuffered streaming
        return FakeProc()

    bundle = R.bench("m", ["x"], out_dir=tmp_path, log=out_lines.append, popen=fake_popen)
    assert bundle == {"results": []}
    assert any("→ solving" in ln for ln in out_lines) and any("ok " in ln for ln in out_lines)


def test_preflight_decision():
    from peakstone.dashboard import preflight, hardware

    class E:                       # stub entry (file size known)
        size_gb, ctx = 3.0, 32768

    assert preflight.vram_needed_gb(E()) == 4.3          # 3.0*1.1 + max(1, 1)
    procs = [hardware.GpuProc(111, 22000)]
    pf = preflight.check(E(), free_gb=2.0, procs=procs)
    assert not pf.fits_now and pf.fits_after_free and pf.freeable_gb == 21.5
    assert preflight.check(E(), free_gb=20.0, procs=[]).fits_now

    class NoSize:                  # not downloaded yet -> can't check -> None (skip pre-flight)
        size_gb, ctx = None, 32768
    assert preflight.check(NoSize(), free_gb=20.0, procs=[]) is None


def test_preflight_screen_actions():
    from peakstone.dashboard import preflight, hardware
    from peakstone.dashboard.app import Dashboard, PreflightScreen
    pf = preflight.Preflight(free_gb=2.0, need_gb=4.3, freeable=[hardware.GpuProc(111, 22000)])
    calls = []

    async def scenario(key):
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.push_screen(PreflightScreen("m", pf, on_proceed=calls.append))
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()

    asyncio.run(scenario("f"))
    asyncio.run(scenario("r"))
    assert calls == [True, False]   # f -> free first, r -> run anyway


def test_run_with_preflight_routing(monkeypatch):
    from peakstone.dashboard import preflight, models, history, hardware
    from peakstone.dashboard import reproduce as R
    from peakstone.dashboard.app import (Dashboard, ModelsScreen, PreflightScreen, ReproduceScreen,
                                         run_with_preflight)
    entry = models.ModelEntry("m", "org/r", "models/m/x.gguf", 8081, 32768, "")
    monkeypatch.setattr(models, "load_registry", lambda: {"m": entry})
    monkeypatch.setattr(models, "available_quants", lambda repo, **k: [])   # no HF network in tests
    monkeypatch.setattr(R, "reproduce", lambda *a, **k: R.ReproduceResult("m", True, note="done"))
    monkeypatch.setattr(history, "append", lambda e: None)

    async def scenario(pf, expect):
        monkeypatch.setattr(preflight, "check", lambda e: pf)
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            scr = ModelsScreen()
            await app.push_screen(scr)
            await pilot.pause()
            run_with_preflight(scr, "m", challenge_ids=["a"], level=None)
            await pilot.pause()
            assert isinstance(app.screen, expect)
            await app.workers.wait_for_complete()
            await pilot.pause()

    tight = preflight.Preflight(2.0, 4.3, [hardware.GpuProc(111, 22000)])
    asyncio.run(scenario(tight, PreflightScreen))       # won't fit -> prompt
    asyncio.run(scenario(preflight.Preflight(20.0, 4.3, []), ReproduceScreen))  # fits -> straight to run


def test_run_queues_when_active():
    from peakstone.dashboard.app import Dashboard

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            app.run_active = True                                  # a run is already in progress
            started = app.start_run("b", challenge_ids=["x"], level="smoke")
            assert started is False                               # second run is queued, not started
            assert [s["name"] for s in app.run_queue] == ["b"] and app.run_queue[0]["level"] == "smoke"

    asyncio.run(scenario())


def test_job_status_tracks_phase_and_progress():
    from peakstone.dashboard.app import Dashboard

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            assert app.job_status() == ""                          # idle
            app.run_queue = [{"name": "a"}]
            assert "1 run(s) queued" in app.job_status()
            app.run_active, app._run_spec, app.run_queue = True, {"name": "qc"}, []
            # parsing the stream drives the global status
            app._track("Running 1 model(s) over 5 challenge(s).")
            assert app._run_total == 5
            app._track("model file missing; downloading…")
            app._dl_done, app._dl_total = 30, 100
            s = app.job_status()
            assert "⬇" in s and "qc" in s and "downloading" in s   # download phase + bar
            app._track("   qc | a   → solving [tests] …")
            app._track("   qc | a   ok  tests 10/10")
            assert app._run_phase == "run" and app._run_done == 1
            assert "▶" in app.job_status() and "1/5" in app.job_status()  # run phase + coverage bar

    asyncio.run(scenario())


def test_download_registers_proc_for_cancel(monkeypatch, tmp_path):
    from peakstone.dashboard import models
    monkeypatch.setattr(models, "REPO", tmp_path)
    monkeypatch.setattr(models, "remote_size", lambda r, f: None)
    monkeypatch.setattr(models.time, "sleep", lambda s: None)
    e = models.ModelEntry("m", "org/r", "models/m/x.gguf", 8081, 32768, "")
    regd = []

    class FakeProc:
        returncode = 0

        def __init__(self):
            self._n = 0

        def poll(self):
            self._n += 1
            return None if self._n == 1 else 0

    models.download(e, popen=lambda *a, **k: FakeProc(), on_proc=regd.append)
    assert len(regd) == 1            # the hf process is registered so a queue-tab cancel can kill it


def test_cancel_active_kills_and_marks(monkeypatch):
    from peakstone.dashboard.app import Dashboard
    from peakstone.dashboard import reproduce as R
    killed = []
    monkeypatch.setattr(R, "stop", killed.append)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            assert app.cancel_active() is False               # nothing running
            app.run_active = True
            app._run_procs = ["serve", "bench"]
            assert app.cancel_active() is True
            assert app._run_cancelled and killed == ["serve", "bench"]   # both subprocesses killed

    asyncio.run(scenario())


def test_quit_warns_only_when_jobs(monkeypatch):
    from peakstone.dashboard.app import Dashboard, ConfirmQuitScreen
    from peakstone.dashboard import reproduce as R
    killed = []
    monkeypatch.setattr(R, "stop", killed.append)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            exited = []
            monkeypatch.setattr(app, "exit", lambda *a, **k: exited.append(True))
            app.action_quit()                                 # no jobs -> quits immediately
            await pilot.pause()
            assert exited == [True] and not isinstance(app.screen, ConfirmQuitScreen)

            app.run_active = True
            app._run_procs = ["p"]
            app.action_quit()                                 # jobs -> confirm first
            await pilot.pause()
            assert isinstance(app.screen, ConfirmQuitScreen)
            await pilot.press("y")                            # confirm -> kill subprocesses + exit
            await pilot.pause()
            assert killed == ["p"] and exited == [True, True]

    asyncio.run(scenario())


def test_queue_screen_manage():
    from peakstone.dashboard.app import Dashboard, QueueScreen
    from textual.widgets import DataTable

    def spec(name, **k):
        return {"name": name, "level": None, "challenge_ids": None, "published_tps": None,
                "free_procs": None, **k}

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            app.run_active = True
            app._run_spec = spec("A", level="smoke")
            app.run_queue = [spec("B", challenge_ids=["x", "y"]), spec("C", level="deep")]
            await app.push_screen(QueueScreen())
            await pilot.pause()
            t = app.screen.query_one("#q-tbl", DataTable)
            assert t.row_count == 3                                   # active + 2 queued
            assert str(t.get_row_at(0)[1]) == "running" and str(t.get_row_at(0)[2]) == "A"
            assert [str(t.get_row_at(i)[2]) for i in (1, 2)] == ["B", "C"]

            t.move_cursor(row=1)                                      # B (first queued)
            await pilot.press("shift+down")                          # reorder B after C
            await pilot.pause()
            assert [s["name"] for s in app.run_queue] == ["C", "B"]

            t.move_cursor(row=1)                                      # C now first queued
            await pilot.press("x")                                   # cancel it
            await pilot.pause()
            assert [s["name"] for s in app.run_queue] == ["B"]

            await pilot.press("c")                                   # clear remaining
            await pilot.pause()
            assert app.run_queue == []

    asyncio.run(scenario())


def test_models_screen_shows_caps(monkeypatch):
    from peakstone.dashboard import models
    from peakstone.dashboard.app import Dashboard, ModelsScreen
    from textual.widgets import Tree
    monkeypatch.setattr("peakstone.engine.capabilities.effective_capabilities",
                        lambda m, **k: {"tools", "agentic"})
    monkeypatch.setattr(models, "available_quants", lambda repo, **k: [])   # no HF network in tests

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(ModelsScreen())
            await pilot.pause()
            t = app.screen.query_one("#models-tree", Tree)
            assert t.root.children                              # families present
            leaves = [str(leaf.label) for fam in t.root.children for leaf in fam.children]
            assert leaves and any(lbl.rstrip().endswith("TA") for lbl in leaves)   # caps in quant label

    asyncio.run(scenario())


def test_level_screen_estimates_and_runs(monkeypatch):
    from peakstone.dashboard import reproduce as R
    from peakstone.dashboard.app import Dashboard, LevelScreen, ReproduceScreen
    from textual.widgets import DataTable
    monkeypatch.setattr("peakstone.engine.estimate.estimate", lambda level, model: {
        "level": level, "model": model, "n_challenges": 42, "by_family": {"humaneval": 42},
        "gen_min": 10.0, "exec_min": 1.0, "download_gb": 0.0, "download_min": 0.0,
        "total_min": 11.0, "tps": 90, "mbps": 50, "unknowns": [], "settings": {}})
    monkeypatch.setattr(R, "reproduce", lambda model, **k: R.ReproduceResult(model, True, your_tps=80.0))
    monkeypatch.setattr("peakstone.dashboard.preflight.check", lambda e: None)   # skip GPU pre-flight

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(LevelScreen("qwen3-coder", "http://x"))
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen.query_one("#lvl-tbl", DataTable).row_count >= 5   # smoke..max
            await pilot.press("r")                                              # run selected level
            await pilot.pause()
            assert isinstance(app.screen, ReproduceScreen) and app._run_spec["level"] is not None

    asyncio.run(scenario())


def test_get_model_client(monkeypatch):
    from peakstone.dashboard import client

    class FakeResp:
        def read(self):
            return b'{"family":"f","runs":[{"run":{"artifact":"Q4"}}]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    captured = {}
    monkeypatch.setattr(client.urllib.request, "urlopen",
                        lambda url, timeout=10: captured.update(url=url) or FakeResp())
    d = client.get_model("http://x", "qwen3-coder")
    assert "/models/qwen3-coder" in captured["url"] and d["runs"][0]["run"]["artifact"] == "Q4"


def test_quant_screen_merges_local_hf_and_leaderboard(monkeypatch):
    from peakstone.dashboard import client, models
    from peakstone.dashboard.app import Dashboard, QuantScreen
    from textual.widgets import DataTable
    entry = models.ModelEntry("qc-q4", "unsloth/QC-GGUF", "models/qc/QC-UD-Q4_K_XL.gguf",
                              8081, 32768, "", "qwen3-coder")
    monkeypatch.setattr(models, "load_registry", lambda: {"qc-q4": entry})
    monkeypatch.setattr(models, "available_quants", lambda repo, **k: [
        {"quant": "UD-Q4_K_XL", "file": "a-UD-Q4_K_XL.gguf", "size_gb": 20.1},
        {"quant": "Q6_K", "file": "a-Q6_K.gguf", "size_gb": 27.0}])
    monkeypatch.setattr(client, "get_model", lambda url, fam, **k: {"runs": [
        {"code_score": 0.9, "held_out_score": 0.6, "agent_score": None, "math_score": 0.5,
         "tok_per_s": 85, "run": {"artifact": "UD-Q4_K_XL", "trust_tier": "community-verified"}}]})

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.push_screen(QuantScreen("qwen3-coder", "http://x", repo="unsloth/QC-GGUF"))
            await app.workers.wait_for_complete()
            await pilot.pause()
            t = app.screen.query_one("#q-tbl", DataTable)
            rows = {str(t.get_row_at(i)[0]): t.get_row_at(i) for i in range(t.row_count)}
            assert set(rows) == {"UD-Q4_K_XL", "Q6_K"}          # registry + HF quants merged
            assert str(rows["UD-Q4_K_XL"][3]) == "0.90"         # leaderboard code score attached
            assert str(rows["Q6_K"][1]) == "· HF" and str(rows["Q6_K"][3]) == "—"   # downloadable, unscored

    asyncio.run(scenario())


def test_dashboard_v_opens_quants(monkeypatch):
    from peakstone.dashboard import client
    from peakstone.dashboard.app import Dashboard, QuantScreen
    monkeypatch.setattr(client, "get_leaderboard", lambda *a, **k: _FAKE)
    monkeypatch.setattr(client, "get_model", lambda url, fam, **k: {"runs": []})

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("v")                       # quants for the selected (row 0) family
            await pilot.pause()
            assert isinstance(app.screen, QuantScreen) and app.screen.family == "qwen3-coder"

    asyncio.run(scenario())


def test_app_handles_api_down(monkeypatch):
    def boom(*a, **k):
        raise client.APIError("connection refused")
    monkeypatch.setattr(client, "get_leaderboard", boom)

    async def scenario():
        app = Dashboard("http://down")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one(DataTable)
            assert table.row_count == 1   # the "API unreachable" row, not a crash

    asyncio.run(scenario())

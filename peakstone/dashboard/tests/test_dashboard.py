"""Dashboard tests — hardware detection + a headless Textual run with a stubbed API."""
from __future__ import annotations

import asyncio

import pytest
from textual.widgets import DataTable, Static

from peakstone.dashboard import client, hardware
from peakstone.dashboard.app import Dashboard, _bar, _fmt

_FAKE = {"count": 2, "leaderboard": [
    {"rank": 1, "family": "qwen3-coder", "code_score": 0.93, "agent_score": None,
     "planner_score": None, "tok_per_s": 85.0,
     "run": {"vram_gb": 24, "trust_tier": "community-verified"}},
    {"rank": 2, "family": "phi-4-mini", "code_score": 0.42, "agent_score": None,
     "planner_score": None, "tok_per_s": 120.0, "run": {"vram_gb": 8, "trust_tier": "self-reported"}},
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
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one(DataTable)
            assert table.row_count == 2
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
                              _download=lambda e, log: True, _serve=lambda n: object(),
                              _wait=lambda p: True, _bench=lambda n, ids: bundle, _stop=lambda p: None)
    assert res.ok and res.your_tps == 85.0 and res.code_score == 0.75
    assert res.passed == 13 and res.total == 20 and res.tps_ratio == 0.85

    # failure paths return a structured result, never raise
    monkeypatch.setattr(models, "load_registry", lambda: {})
    assert reproduce.reproduce("ghost", challenge_ids=["a"]).ok is False
    monkeypatch.setattr(models, "load_registry", lambda: {"m": entry})
    unhealthy = reproduce.reproduce("m", challenge_ids=["a"], _download=lambda e, log: True,
                                    _serve=lambda n: object(), _wait=lambda p: False,
                                    _bench=lambda n, ids: bundle, _stop=lambda p: None)
    assert unhealthy.ok is False and "healthy" in unhealthy.note


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
            await app.push_screen(ReproduceScreen("qwen3-coder", 100.0, "http://x"))
            await app.workers.wait_for_complete()
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
    from peakstone.dashboard import history
    from peakstone.dashboard import reproduce as R
    from peakstone.dashboard.app import Dashboard, ModelsScreen, ReproduceScreen
    monkeypatch.setattr(R, "reproduce", lambda model, **k: R.ReproduceResult(model, True, your_tps=70.0, note="done"))
    monkeypatch.setattr(history, "append", lambda e: None)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(ModelsScreen())   # the real registry has models -> a selectable row
            await pilot.pause()
            await pilot.press("r")                   # run the selected model
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


def test_models_screen_shows_caps(monkeypatch):
    from peakstone.dashboard.app import Dashboard, ModelsScreen
    from textual.widgets import DataTable
    monkeypatch.setattr("peakstone.engine.capabilities.effective_capabilities",
                        lambda m, **k: {"tools", "agentic"})

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            await app.push_screen(ModelsScreen())
            await pilot.pause()
            t = app.screen.query_one("#models-tbl", DataTable)
            assert t.row_count > 0
            assert "Caps" in [str(c.label) for c in t.columns.values()]
            assert any(str(t.get_row_at(i)[5]) == "TA" for i in range(t.row_count))  # caps col

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
            assert isinstance(app.screen, ReproduceScreen) and app.screen.level is not None

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

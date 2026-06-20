"""Dashboard tests — hardware detection + a headless Textual run with a stubbed API."""
from __future__ import annotations

import asyncio

import pytest
from textual.widgets import DataTable, Static

from dashboard import client, hardware
from dashboard.app import Dashboard, _bar, _fmt

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
            assert captured["sort"] == "agent_score"
            # toggling the fit filter off drops the VRAM scope
            await pilot.press("f")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert captured["max_vram_gb"] is None

    asyncio.run(scenario())


def test_registry_add_and_list(monkeypatch, tmp_path):
    from dashboard import models
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


def test_download_invokes_hf(monkeypatch, tmp_path):
    from dashboard import models
    monkeypatch.setattr(models, "REPO", tmp_path)
    e = models.ModelEntry("m", "org/repo", "models/m/x.gguf", 8081, 32768, "")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stderr": ""})()

    models.download(e, runner=fake_run)
    assert calls["cmd"][:3] == ["hf", "download", "org/repo"] and "--local-dir" in calls["cmd"]


def test_reproduce_orchestration(monkeypatch):
    from dashboard import models, reproduce
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


def test_reproduce_screen_shows_result(monkeypatch):
    from dashboard import reproduce as R
    from dashboard.app import Dashboard, ReproduceScreen
    monkeypatch.setattr(R, "reproduce", lambda model, **k: R.ReproduceResult(
        model, True, your_tps=80.0, published_tps=100.0, code_score=0.9, passed=9, total=10, note="done"))

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.push_screen(ReproduceScreen("qwen3-coder", 100.0))
            await app.workers.wait_for_complete()
            await pilot.pause()
            result = str(app.screen.query_one("#repro-result", Static).render())
            assert "80" in result and "0.8" in result   # your tps (80) + ratio vs published (80/100)

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

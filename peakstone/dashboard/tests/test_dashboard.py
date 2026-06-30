"""Dashboard tests — hardware detection + a headless Textual run with a stubbed API."""
from __future__ import annotations

import asyncio
import time

import pytest
from textual.widgets import DataTable, Static

from peakstone.dashboard import client, hardware
from peakstone.dashboard import models as _models
from peakstone.dashboard.app import Dashboard, _bar, _fmt

# Captured before any stubbing so the cache-path test can call the real implementation.
_REAL_AVAILABLE_QUANTS = _models.available_quants


def _stub_daemon(monkeypatch, *, status="done", summary=None, lines=(), enqueued=None,
                 bundle=None, repo=None):
    """Simulate the gateway daemon so the TUI (a pure frontend) can be tested without a real
    `peakstone serve`. The TUI enqueues a run, then ADOPTS+MIRRORS whatever the daemon reports as
    running — so the stub is stateful: enqueue makes a job show up "running" in list_jobs, get_job
    (called once the mirror's log stream ends) flips it terminal with `summary`. Downloads complete
    immediately. `enqueued` collects run specs; `bundle`/`repo` write a bundle.json for the submit path."""
    import json as _json
    from peakstone.dashboard import client as _client
    from peakstone.gateway import launch as _launch
    summary = summary or {}
    state: dict = {"jobs": [], "n": 0}

    def enqueue(spec, *, kind="run", **k):
        state["n"] += 1
        jid = f"job{state['n']}"
        if kind == "run" and enqueued is not None:
            enqueued.append(spec)
        if kind == "run" and bundle is not None and repo is not None:
            out = repo / "results" / f"job-{jid}"
            out.mkdir(parents=True, exist_ok=True)
            (out / "bundle.json").write_text(_json.dumps(bundle))
        # runs start "running" so the TUI adopts + mirrors them; downloads finish immediately
        state["jobs"].append({"id": jid, "kind": kind, "spec": spec, "created": state["n"],
                              "status": "running" if kind == "run" else "done",
                              "summary": summary if kind == "run" else {"note": "downloaded"}})
        return jid

    def get_job(jid, **k):
        for j in state["jobs"]:
            if j["id"] == jid:
                if j["kind"] == "run":             # the mirror finished → job reaches its terminal state
                    j["status"], j["summary"] = status, summary
                return dict(j)
        return None

    def cancel_job(jid, **k):
        for j in state["jobs"]:
            if j["id"] == jid:
                j["status"] = "cancelled"
        return True

    monkeypatch.setattr(_launch, "ensure_running", lambda *a, **k: True)
    monkeypatch.setattr(_client, "enqueue_job", enqueue)
    monkeypatch.setattr(_client, "download_model",
                        lambda m, **k: enqueue({"model": m}, kind="download"))
    monkeypatch.setattr(_client, "stream_job_log", lambda j, **k: iter(lines))
    monkeypatch.setattr(_client, "get_job", get_job)
    monkeypatch.setattr(_client, "cancel_job", cancel_job)
    monkeypatch.setattr(_client, "list_jobs", lambda **k: [dict(j) for j in state["jobs"]])


@pytest.fixture(autouse=True)
def _no_hf_network(monkeypatch):
    """The models screen auto-expands families, which kicks off HF quant discovery in worker threads;
    keep that off the network in tests (a real lookup would block worker shutdown at app exit)."""
    monkeypatch.setattr(_models, "available_quants", lambda repo, **k: [])
    # The dashboard talks to the gateway over these client calls; stub them all so NO test can reach a
    # real local `peakstone serve` (polling adopts, and the download/run menus enqueue). _stub_daemon
    # overrides with a stateful fake when a run is actually exercised.
    from peakstone.dashboard import client as _client
    monkeypatch.setattr(_client, "list_jobs", lambda **k: [])
    monkeypatch.setattr(_client, "enqueue_job", lambda spec, **k: "stub-job")
    monkeypatch.setattr(_client, "download_model", lambda m, **k: "stub-dl")
    monkeypatch.setattr(_client, "cancel_job", lambda jid, **k: True)
    monkeypatch.setattr(_client, "get_job", lambda jid, **k: None)
    monkeypatch.setattr(_client, "stream_job_log", lambda jid, **k: iter(()))
    from peakstone.gateway import launch as _launch
    monkeypatch.setattr(_launch, "ensure_running", lambda *a, **k: True)   # never spawn a real daemon

_FAKE = {"count": 2, "leaderboard": [
    {"rank": 1, "family": "qwen3-coder", "code_score": 0.93, "agent_score": None,
     "planner_score": None, "tok_per_s": 85.0, "sol_per_s": 0.5, "n_total": 50,
     "run": {"vram_gb": 24, "ram_gb": 64, "vram_used_gb": 24, "ram_used_gb": 26, "context": 32768,
             "gpu": "NVIDIA GeForce RTX 4090", "cpu": "AMD Ryzen 9 7950X 16-Core Processor",
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
    from peakstone.dashboard.app import _mem, _hw, _short_gpu, _short_cpu, _ctx_k
    assert _mem(24, 26) == "24/26 GB" and _mem(24, None) == "24 GB" and _mem(None, None) == "?"
    assert _ctx_k(32768) == "32K" and _ctx_k(65536) == "64K" and _ctx_k(None) == "—"
    assert _short_gpu("NVIDIA GeForce RTX 4090") == "RTX 4090"
    assert _short_cpu("AMD Ryzen 9 7950X 16-Core Processor") == "AMD Ryzen 9 7950X"
    assert _hw({"gpu": "NVIDIA GeForce RTX 4090", "vram_gb": 24,
                "cpu": "Intel(R) Core(TM) i9-13900K", "ram_gb": 64}) == "RTX 4090 24G · Intel Core i9-13900K 64G"
    assert _hw({}) == ""


def test_model_output_brackets_never_crash_markup():
    """Regression: a reasoner's chain-of-thought is full of brackets/backticks that crashed Rich's
    markup parser mid-run (MarkupError on shapes like `[^[]`). Both render paths must survive it and
    render the brackets verbatim — escape() alone did not."""
    from rich.console import Console
    from rich.text import Text
    from peakstone.dashboard.app import _pretty_progress
    c = Console(width=100, file=None)
    nasty = [r"if tok[0] == 'NUMBER': arr[1:] and [^[]*? `chars` empty.",
             r"regex \d+ \n and a path C:\Users\x[0]", "[/] [b] [red] ]]] unmatched"]
    for s in nasty:
        with c.capture() as cap:                       # log path: must not raise, brackets verbatim
            c.print(_pretty_progress("  ok  " + s))
        assert s in cap.get()
        t = Text("solving\n"); t.append_text(Text(s))  # gen-panel path: Text is never markup-parsed
        with c.capture() as cap:
            c.print(t)
        assert s in cap.get()


def test_app_renders_filtered_leaderboard(monkeypatch):
    captured = {}

    def fake_get(base_url, *, max_vram_gb=None, sort="code_score", collapse="family", timeout=10):
        captured["max_vram_gb"] = max_vram_gb
        captured["sort"] = sort
        captured["collapse"] = collapse
        return _FAKE

    monkeypatch.setattr(client, "get_leaderboard", fake_get)

    async def scenario():
        from peakstone.dashboard.app import BoardTree
        app = Dashboard("http://test")
        async with app.run_test() as pilot:
            app._corpus = [None] * 1965          # pin the coverage denominator (corpus grows over time)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert captured["collapse"] == "quant"             # board always fetches per-quant rows
            tree = app.query_one("#board", BoardTree)
            fam_labels = [str(n.label) for n in tree.root.children]
            assert len(fam_labels) == 2                        # one node per model family
            assert any("qwen3-coder" in lbl for lbl in fam_labels)
            # the model's quant run is nested under it with its metrics + hardware
            leaf = str(tree.root.children[0].children[0].label)
            assert "24/26 GB" in leaf and "50/1965" in leaf and "32K ctx" in leaf
            assert "RTX 4090 24G" in leaf and "Ryzen 9 7950X 64G" in leaf   # hardware it ran on
            # the board defaults to the held-out lens; cycling sort moves to the next axis
            assert captured["sort"] == "held_out_score"        # default lens
            await pilot.press("s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert captured["sort"] == "code_score"            # next axis after cycling
            # toggling the fit filter off drops the VRAM scope
            await pilot.press("f")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert captured["max_vram_gb"] is None

    asyncio.run(scenario())


def test_board_quant_groups_results_like_peakstones(monkeypatch):
    from peakstone.dashboard.app import Dashboard, BoardTree, SolutionScreen
    from textual.widgets import Static
    LB = {"count": 1, "leaderboard": [{"family": "qz", "code_score": 0.7, "tok_per_s": 80, "n_total": 2,
          "run": {"artifact": "Q6_K", "bundle_hash": "bh1", "vram_gb": 24}}]}
    monkeypatch.setattr(client, "get_leaderboard", lambda *a, **k: LB)
    # real native corpus ids, so they group under Native -> date -> family like the peakstones window
    monkeypatch.setattr(client, "get_run", lambda url, bh, **k: {"results": [   # lite: scores only
        {"challenge": "py-05-calc", "final": 1.0, "passed": 10, "total": 10, "category": "code"},
        {"challenge": "go-03-detect-cycle", "final": 0.0, "passed": 0, "total": 1, "category": "code"}]})
    monkeypatch.setattr(client, "get_run_challenge", lambda url, bh, cid, **k: {   # transcript on demand
        "challenge": cid, "final": 1.0, "passed": 10, "total": 10,
        "transcript": {"raw_output": "def solution(): return 42", "stdout": "all tests passed"}})

    def leaves(node):
        out = []
        for c in node.children:
            out.append(str(c.label))
            out += leaves(c)
        return out

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            t = app.query_one("#board", BoardTree)
            fam = t.root.children[0]
            fam.expand()
            await pilot.pause()
            quant = fam.children[0]
            quant.expand()                                 # drill into the run's per-challenge results
            await app.workers.wait_for_complete()
            await pilot.pause()
            # grouped like the challenges browser: collection -> date -> family -> challenge, with avg scores
            assert any("Peakstone" in str(c.label) and "0.50" in str(c.label) for c in quant.children)
            allnodes = leaves(quant)
            assert any("2026-06" in n for n in allnodes)
            assert any("python" in n and "1.00" in n for n in allnodes)   # family avg score
            assert any("py-05-calc" in n for n in allnodes) and any("go-03-detect-cycle" in n for n in allnodes)
            # opening a test result fetches the transcript on demand and shows solution + output + reaction
            app.open_solution({"row": {"challenge": "py-05-calc"}, "bundle_hash": "bh1"})
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            out = str(app.screen.query_one("#sol-out", Static).render())
            assert isinstance(app.screen, SolutionScreen) and "def solution(): return 42" in out
            assert "all tests passed" in out and "PASS" in out and "10/10" in out

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


def test_download_streams_with_progress(monkeypatch, tmp_path):
    from pathlib import Path
    from peakstone.dashboard import models
    monkeypatch.setattr(models, "REPO", tmp_path)
    monkeypatch.setattr(models, "remote_size", lambda r, f: 1000)   # seeds the bar without a network call
    e = models.ModelEntry("m", "org/repo", "models/m/x.gguf", 8081, 32768, "")
    progress = []

    def fake_fetch(repo, filename, local_dir, *, progress, cancel, log):
        assert repo == "org/repo" and filename == "x.gguf"
        progress(400, 1000)                            # byte-accurate updates as bytes arrive
        progress(1000, 1000)
        (Path(local_dir) / filename).write_bytes(b"x" * 1000)   # hf materializes the file

    ok = models.download(e, progress=lambda d, t: progress.append((d, t)), _fetch=fake_fetch)
    assert ok is True and e.present                     # file materialized
    assert progress[0] == (0, 1000)                     # size shown immediately during the quiet startup
    assert progress[1] == (400, 1000) and progress[-1] == (1000, 1000)  # byte-accurate updates


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


def test_bench_threads_generation_budget(tmp_path):
    """The TUI budget picker -> reproduce.bench -> the runner's --max-tokens flag (recorded in the
    bundle). Present only when a budget is chosen; absent (engine default) otherwise."""
    from peakstone.dashboard import reproduce

    class FakeProc:
        def __init__(self):
            self.stdout = iter(())          # no streamed lines; we only inspect the launched command
        def wait(self):
            return 0
        def poll(self):
            return 0

    captured = {}
    def fake_popen(cmd, **k):
        captured["cmd"] = cmd
        return FakeProc()

    reproduce.bench("m", ["a"], out_dir=tmp_path, popen=fake_popen, max_tokens=24576)
    assert "--max-tokens" in captured["cmd"] and "24576" in captured["cmd"]

    reproduce.bench("m", ["a"], out_dir=tmp_path, popen=fake_popen, max_tokens=None)
    assert "--max-tokens" not in captured["cmd"]   # no override -> engine's generous default applies


def test_gen_phase_drives_overview_status():
    from peakstone.dashboard.app import Dashboard, GEN_PHASE
    app = Dashboard.__new__(Dashboard)
    import threading
    from collections import deque
    app._run_lock = threading.Lock()
    app.run_active = True
    app._daemon_jobs = []
    app._run_spec = {"name": "m"}
    app._run_phase, app._run_done, app._run_total = "run", 3, 200
    app._run_t0, app._run_tps, app._run_gen_phase = None, 48.0, None
    app._dl_done = app._dl_total = 0

    app._track(GEN_PHASE + "thinking")          # a phase line from the stream
    assert app.run_progress()["gen_phase"] == "thinking"
    # phase + tok/s + coverage all ride on the model line (concise); the bottom row stays empty
    assert "thinking" in app.run_status_inline() and "48 tok/s" in app.run_status_inline()
    assert "3/200 challenges" in app.run_status_inline()
    assert app.job_status() == ""                # no separate "running" line — inferred by the phase
    app._track(GEN_PHASE + "answering")
    assert "answering" in app.run_status_inline()
    app._track("   m | c1   ok  final=1.00 tests=3/3 50tok/s")   # challenge done -> phase cleared
    assert app.run_progress()["gen_phase"] is None


def test_reasoning_budget_mapping_and_threading(monkeypatch, tmp_path):
    """The reasoning override -> PEAKSTONE_REASONING_BUDGET: off=0, full=-1, and a numeric thinking
    cap passes through verbatim (capping thinking, leaving room for the answer)."""
    from peakstone.dashboard import reproduce
    assert reproduce._reasoning_budget("off") == "0"
    assert reproduce._reasoning_budget("on") == "-1"
    assert reproduce._reasoning_budget(4096) == "4096"      # numeric thinking budget
    assert reproduce._reasoning_budget(None) is None and reproduce._reasoning_budget(0) is None

    class FakeProc:
        def __init__(self):
            self.stdout = iter(())
        def wait(self):
            return 0
        def poll(self):
            return 0

    captured = {}
    def fake_popen(cmd, **k):
        captured["env"] = k.get("env", {})
        return FakeProc()

    reproduce.bench("m", ["a"], out_dir=tmp_path, popen=fake_popen, reasoning=4096)
    assert captured["env"].get("PEAKSTONE_REASONING_BUDGET") == "4096"
    reproduce.bench("m", ["a"], out_dir=tmp_path, popen=fake_popen, reasoning=None)
    assert "PEAKSTONE_REASONING_BUDGET" not in captured["env"]   # default -> no override


def test_budget_for_resolves_override_then_default():
    from peakstone.dashboard.app import Dashboard
    app = Dashboard.__new__(Dashboard)
    app.budget_overrides = {}
    assert app.budget_for("m") is None                 # nothing set -> engine default
    app.budget_overrides[""] = 16384                   # global default
    assert app.budget_for("m") == 16384
    app.budget_overrides["m"] = 32768                  # per-model override wins
    assert app.budget_for("m") == 32768 and app.budget_for("other") == 16384


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
                              _download=lambda e, log, **k: True, _serve=lambda n, **k: object(),
                              _wait=lambda p, **k: True, _bench=lambda n, ids, **k: bundle, _stop=lambda p: None)
    assert res.ok and res.your_tps == 85.0 and res.code_score == 0.75
    assert res.passed == 13 and res.total == 20 and res.tps_ratio == 0.85

    # failure paths return a structured result, never raise
    monkeypatch.setattr(models, "load_registry", lambda: {})
    assert reproduce.reproduce("ghost", challenge_ids=["a"]).ok is False
    monkeypatch.setattr(models, "load_registry", lambda: {"m": entry})
    unhealthy = reproduce.reproduce("m", challenge_ids=["a"], _download=lambda e, log, **k: True,
                                    _serve=lambda n, **k: object(), _wait=lambda p, **k: False,
                                    _bench=lambda n, ids, **k: bundle, _stop=lambda p: None)
    assert unhealthy.ok is False and "healthy" in unhealthy.note

    # a crashed serve process (poll() returns an exit code) fails fast with the crash reason, not "healthy"
    class _Dead:
        def poll(self):
            return 1
    crashed = reproduce.reproduce("m", challenge_ids=["a"], _download=lambda e, log, **k: True,
                                  _serve=lambda n, **k: _Dead(), _wait=lambda p, proc=None: False,
                                  _bench=lambda n, ids, **k: bundle, _stop=lambda p: None)
    assert crashed.ok is False and "exited before serving" in crashed.note


def test_viewer_never_crashes_on_bad_lines(monkeypatch):
    """The hard guarantee for long runs: NOTHING streamed from the runner — not crash-shaped model
    output, not even a line that makes our own renderer throw — may propagate out of the _drain_log
    UI timer, because an unhandled exception there tears down the whole TUI mid-run. Feed the exact
    markup crash shape AND a line forced to raise; the viewer must survive and keep rendering."""
    from collections import deque
    from peakstone.dashboard.app import Dashboard, ReproduceScreen, GEN_MARK

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            app._run_spec = {"name": "m", "level": "standard"}
            app._run_log, app._run_log_n = deque(), 0
            screen = ReproduceScreen()
            await app.push_screen(screen)
            await pilot.pause()
            screen.reset_view()

            poison = "POISON_FORCE_RAISE"
            real_on_line = screen._on_line
            def maybe_boom(s):                       # force a renderer failure on one specific line
                if s == poison:
                    raise ValueError("simulated render bug")
                return real_on_line(s)
            monkeypatch.setattr(screen, "_on_line", maybe_boom)

            for ln in [GEN_MARK + "reasoning: regex [^[]*? then tok[0] and `chars` empty.",
                       poison,
                       "  m | he-001  ok  final=1.00 tests=3/3 120tok/s"]:
                app._run_log.append(ln)
                app._run_log_n += 1

            screen._drain_log()                      # must NOT raise despite the poison line
            await pilot.pause()
            # the crash-shaped chain-of-thought rendered verbatim (not crashed, not mangled)
            gen = str(screen.query_one("#repro-gen", Static).render())
            assert "[^[]*?" in gen and "tok[0]" in gen

    asyncio.run(scenario())


def test_reproduce_screen_shows_result_and_records_history(monkeypatch, tmp_path):
    from peakstone.dashboard import history
    from peakstone.dashboard.app import Dashboard, ReproduceScreen
    monkeypatch.setenv("PEAKSTONE_REPO", str(tmp_path))             # bundle read/write lands in tmp
    # the run executes in the daemon; stub it to return a finished job (+ a bundle on disk for submit)
    _stub_daemon(monkeypatch, summary={"your_tps": 80.0, "code_score": 0.9, "passed": 9, "total": 10,
                                       "submitted": None},
                 bundle={"bundle_version": "1"}, repo=tmp_path)
    recorded = []
    monkeypatch.setattr(history, "append", recorded.append)
    submitted = {}

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            app.start_run("qwen3-coder", published_tps=100.0)        # app-level run manager
            await app.workers.wait_for_complete()                    # run completes on the app worker
            await app.push_screen(ReproduceScreen())                 # viewer backfills the finished run
            await pilot.pause()
            result = str(app.screen.query_one("#repro-result", Static).render())
            assert "80" in result and "0.9" in result and "submit" in result
            # the run was recorded in history
            assert recorded and recorded[0]["model"] == "qwen3-coder" and recorded[0]["your_tps"] == 80.0
            # pressing 's' re-submits the daemon-produced bundle (read off disk)
            from peakstone.dashboard import client
            monkeypatch.setattr(client, "submit_bundle", lambda url, b, **k: submitted.update(b=b) or (201, "ok"))
            await pilot.press("s")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert submitted.get("b") == {"bundle_version": "1"}

    asyncio.run(scenario())


def test_adopts_cli_launched_daemon_job(monkeypatch):
    """A benchmark queued via the `peakstone jobs` CLI runs in the daemon; the TUI should adopt it on
    mount and mirror its live output, even though it didn't start it."""
    from peakstone.dashboard.app import Dashboard
    from peakstone.dashboard import client, history
    _stub_daemon(monkeypatch, summary={"your_tps": 42.0, "code_score": 0.8, "passed": 8, "total": 10},
                 lines=["benchmarking qwen3-coder over 10 challenges", "  ok unique | 1.0 | 50 tok/s"])
    # The daemon is running a job this TUI didn't start. list_jobs keeps reporting it until get_job
    # (called once the mirror finishes) flips it to done — so the loop adopts it exactly once.
    job = {"id": "testjob", "status": "running", "spec": {"model": "qwen3-coder", "level": "standard"}}
    monkeypatch.setattr(client, "list_jobs", lambda **k: [dict(job)])

    def get_job(j, **k):
        job["status"] = "done"
        return {"id": j, "status": "done",
                "summary": {"your_tps": 42.0, "code_score": 0.8, "passed": 8, "total": 10}}
    monkeypatch.setattr(client, "get_job", get_job)
    recorded = []
    monkeypatch.setattr(history, "append", recorded.append)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            await app.workers.wait_for_complete()      # on_mount poll adopts + mirrors the daemon job
            assert recorded and recorded[0]["model"] == "qwen3-coder"
            assert app._run_result is not None and app._run_result.model == "qwen3-coder"
            assert app._run_done > 0                    # coverage was reconstructed from the streamed log

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
    # native first (our authored 'Peakstone' collection collapsed), then imported suites largest-first
    assert kinds == [("native", "Peakstone", 1), ("suite", "livecodebench", 2), ("suite", "humaneval", 1)]
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
            await pilot.press("c")              # clear the default-selected 'standard' level first
            await pilot.pause()
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
    enqueued = []
    _stub_daemon(monkeypatch, enqueued=enqueued)

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
            await pilot.press("y")                     # confirm -> queue the run on the daemon
            await pilot.pause()
            await app.workers.wait_for_complete()
            assert [s["model"] for s in enqueued] == ["m-q4"]   # the run was queued on the daemon

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
    from textual.widgets import Static, DataTable

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            scr = ReproduceScreen()
            await app.push_screen(scr)
            await pilot.pause()
            scr._on_line("   m | py-05-calc          → solving [tests] …")   # sets the live challenge
            scr._on_line(GEN_MARK + "def f():" + GEN_NL + "  return 1")       # gen delta -> output panel
            scr._on_line(GEN_MARK + " more")
            scr._on_line("   m | py-05-calc          ok  final=1.00 tests=10/10")   # result -> table row
            await pilot.pause()
            gen = str(scr.query_one("#repro-gen", Static).render())
            assert "py-05-calc" in gen and "def f():\n  return 1 more" in gen and GEN_MARK not in gen
            # the completed test is a row in the navigable table (not a scrolling log)
            tbl = scr.query_one("#repro-completed", DataTable)
            assert "py-05-calc" in scr._completed and tbl.row_count == 2   # live row + the result

            # completed tests sit at the top; the live/current row is pinned to the BOTTOM.
            # selecting the completed row brings up THAT test's captured solution for review
            tbl.focus()
            tbl.move_cursor(row=0)               # the completed test (top)
            await pilot.pause()
            assert scr._viewing == "py-05-calc"
            review = str(scr.query_one("#repro-gen", Static).render())
            assert "proposed solution" in review and "def f():\n  return 1 more" in review

            # moving down to the live row (bottom) resumes following live generation
            tbl.move_cursor(row=1)
            await pilot.pause()
            assert scr._viewing is None

    asyncio.run(scenario())


def test_reproduce_output_does_not_force_scroll_when_user_scrolled_up():
    """Long-run readability: once the user scrolls up to read, streaming deltas must NOT yank the
    output back to the bottom. _set_output only pins to the end if the view was already there."""
    from peakstone.dashboard.app import Dashboard, ReproduceScreen, GEN_MARK
    from textual.containers import VerticalScroll

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            scr = ReproduceScreen()
            await app.push_screen(scr)
            await pilot.pause()
            scr._on_line("   m | c1          → solving [tests] …")
            for i in range(400):                 # enough output to make the panel scrollable
                scr._on_line(GEN_MARK + f"line {i} of generated reasoning and code")
            await pilot.pause()
            wrap = scr.query_one("#repro-gen-wrap", VerticalScroll)
            wrap.scroll_to(y=0, animate=False)    # user scrolls to the top to read
            await pilot.pause()
            scr._on_line(GEN_MARK + "a freshly streamed delta")   # more generation arrives
            await pilot.pause()
            assert wrap.scroll_y < wrap.max_scroll_y - 2          # NOT yanked to the bottom

    asyncio.run(scenario())


def test_reproduce_screen_coverage_and_rate():
    from peakstone.dashboard.app import Dashboard, ReproduceScreen
    from textual.widgets import Static

    async def scenario():
        app = Dashboard("http://x")
        app._corpus = [None] * 1965                                           # fixed suite denominator
        # app owns the run counters now; the viewer just renders run_progress()
        app._run_total, app._run_done, app._run_t0 = 3, 2, time.monotonic()
        async with app.run_test() as pilot:
            scr = ReproduceScreen()
            await app.push_screen(scr)
            await pilot.pause()
            scr._update_stat()
            stat = str(scr.query_one("#repro-stat", Static).render())
            assert "coverage 2/3" in stat and "3/1965 of suite" in stat and "sol/s" in stat

    asyncio.run(scenario())


def test_repetition_loop_shows_as_error_type():
    from peakstone.dashboard.app import Dashboard, _solution_body
    leaf = Dashboard._result_leaf({"challenge": "c1", "final": 0.0,    # lite leaf: top-level error
                                   "error": "repetition-loop"})
    assert "⟳" in leaf and "repetition loop" in leaf          # distinct marker, not a plain ✗
    body = _solution_body({"challenge": "c1", "final": 0.0,
                           "transcript": {"error": "repetition-loop", "raw_output": "loop loop"}})
    assert "REPETITION LOOP" in body


def test_fmt_dur():
    from peakstone.dashboard.app import _fmt_dur
    assert _fmt_dur(45) == "45s"
    assert _fmt_dur(192) == "3m12s"
    assert _fmt_dur(3725) == "1h02m"
    assert _fmt_dur(None) == "—" and _fmt_dur(0) == "—"


def test_ctx_picker_caps_skips_and_selects():
    from peakstone.dashboard.app import Dashboard, CtxScreen
    from peakstone.dashboard import models as _m
    from textual.widgets import DataTable

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            app.selected_ids = ["lc-01-buried-routes"]          # a min_ctx=16384 long-context challenge
            entry = _m.ModelEntry("m", "r", "models/m/x.gguf", 8081, 32768, "")  # native 32K
            scr = CtxScreen(entry, "m", None)                    # per-model key = "m"
            await app.push_screen(scr)
            await pilot.pause()
            t = app.screen.query_one("#ctx-tbl", DataTable)
            labels = " ".join(str(t.get_row_at(i)[1]) for i in range(t.row_count))
            assert "32K" in labels and "64K" not in labels and "128K" not in labels   # capped at native
            assert scr._rows == [None, 4096, 8192, 16384, 32768]
            # the 8K option would skip the 16K long-context challenge; 32K skips none
            assert "skips 1" in str(t.get_row_at(2)[3])          # 8192 row
            assert "skips" not in str(t.get_row_at(4)[3])        # 32768 row
            # selecting the 16K row sets this model's ctx and closes
            t.move_cursor(row=3)
            scr.action_choose()
            await pilot.pause()
            assert app.ctx_for("m") == 16384 and app.ctx_overrides["m"] == 16384

    asyncio.run(scenario())


def test_ctx_is_per_model():
    from peakstone.dashboard.app import Dashboard
    app = Dashboard("http://x")
    app.ctx_overrides[""] = 8192            # global default
    app.ctx_overrides["big-model"] = 131072  # per-model override
    assert app.ctx_for("big-model") == 131072
    assert app.ctx_for("other-model") == 8192   # falls back to the global default
    del app.ctx_overrides[""]
    assert app.ctx_for("other-model") is None   # no default -> native ctx


def test_quant_label_shows_efficiency():
    from peakstone.dashboard.app import Dashboard
    app = Dashboard("http://x")
    label = app._quant_label({"code_score": 0.7, "score_per_1k_tokens": 0.42, "n_ctx_limited": 3,
                              "n_total": 2, "run": {"artifact": "Q6_K", "context": 32768}})
    assert "0.42/1k tok" in label and "⚠3" in label          # efficiency + ctx-limited warning
    clean = app._quant_label({"code_score": 0.7, "score_per_1k_tokens": 0.42, "n_ctx_limited": 0,
                              "run": {"artifact": "Q6_K"}})
    assert "0.42/1k tok" in clean and "⚠" not in clean       # no warning when nothing was truncated


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
    monkeypatch.setattr(history, "append", lambda e: None)
    _stub_daemon(monkeypatch)                       # runs go to the (stubbed) daemon

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


def test_run_ctx_selection_threads_through(monkeypatch):
    from peakstone.dashboard import models, history
    from peakstone.dashboard.app import Dashboard, ModelsScreen, CTX_CHOICES, run_with_preflight
    entry = models.ModelEntry("m", "org/r", "models/m/x.gguf", 8081, 32768, "")
    monkeypatch.setattr(models, "load_registry", lambda: {"m": entry})
    monkeypatch.setattr(models, "available_quants", lambda repo, **k: [])
    monkeypatch.setattr("peakstone.dashboard.preflight.check", lambda e: None)
    monkeypatch.setattr(history, "append", lambda e: None)
    enqueued = []
    _stub_daemon(monkeypatch, enqueued=enqueued)

    async def scenario():
        from peakstone.dashboard.app import CtxScreen
        from textual.widgets import DataTable
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            scr = ModelsScreen()
            await app.push_screen(scr)
            await pilot.pause()
            await pilot.press("k")                              # open the ctx picker
            await pilot.pause()
            assert isinstance(app.screen, CtxScreen)
            t = app.screen.query_one("#ctx-tbl", DataTable)
            t.move_cursor(row=1)                                # [default, 4096, …] -> pick 4096
            app.screen.action_choose()
            await pilot.pause()
            assert app.ctx_for("m") == CTX_CHOICES[1]
            run_with_preflight(scr, "m")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert enqueued and enqueued[0].get("ctx") == CTX_CHOICES[1]   # chosen ctx → job spec

    asyncio.run(scenario())


def test_serve_passes_ctx_env(monkeypatch, tmp_path):
    from peakstone.dashboard import reproduce as R
    monkeypatch.setattr(R, "REPO", tmp_path)
    (tmp_path / "results").mkdir()
    captured = {}

    class P:
        def wait(self):
            return 0

    def fake_popen(cmd, **kw):
        captured["env"] = kw.get("env", {})
        return P()

    R.serve("m", popen=fake_popen, ctx=8192)
    assert captured["env"].get("PEAKSTONE_CTX") == "8192"


def test_bundle_ctx_override(monkeypatch):
    from peakstone.engine.bundle import _ctx_override
    assert _ctx_override(32768) == 32768                        # no env -> configured default
    monkeypatch.setenv("PEAKSTONE_CTX", "8192")
    assert _ctx_override(32768) == 8192                         # env overrides


def test_run_enqueues_on_daemon_even_when_active(monkeypatch):
    from peakstone.dashboard.app import Dashboard
    enqueued = []
    _stub_daemon(monkeypatch, enqueued=enqueued)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            app.run_active = True                                  # already mirroring a run
            jid = app.start_run("b", challenge_ids=["x"], level="smoke")
            assert jid                                             # still enqueued (the daemon serializes)
            assert enqueued[-1]["model"] == "b" and enqueued[-1]["level"] == "smoke"

    asyncio.run(scenario())


def test_download_queues_on_daemon(monkeypatch):
    from peakstone.dashboard.app import Dashboard
    from peakstone.dashboard import client
    _stub_daemon(monkeypatch)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            jid = app.start_download("phi-q2")
            assert jid                                             # queued on the separate download queue
            dl = [j for j in client.list_jobs() if j.get("kind") == "download"]
            assert dl and dl[0]["spec"]["model"] == "phi-q2"

    asyncio.run(scenario())


def test_job_status_tracks_phase_and_progress():
    from peakstone.dashboard.app import Dashboard

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            assert app.job_status() == ""                          # idle
            app._daemon_jobs = [{"id": "j", "kind": "run", "status": "queued", "spec": {"model": "a"}}]
            assert "1 run(s) queued" in app.job_status()
            app.run_active, app._run_spec, app._daemon_jobs = True, {"name": "qc"}, []
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
            # coverage rides the model line now; the bottom row is empty for a running benchmark
            assert "1/5 challenges" in app.run_status_inline() and app.job_status() == ""

    asyncio.run(scenario())


def test_download_cancels_cooperatively(monkeypatch, tmp_path):
    from peakstone.dashboard import models
    monkeypatch.setattr(models, "REPO", tmp_path)
    monkeypatch.setattr(models, "remote_size", lambda r, f: 1000)
    e = models.ModelEntry("m", "org/r", "models/m/x.gguf", 8081, 32768, "")

    def fake_fetch(repo, filename, local_dir, *, progress, cancel, log):
        # mimic the real tap: per-chunk, report progress then honour cancel by raising _Cancelled
        for i in range(100):
            progress(i * 10, 1000)
            if cancel and cancel():
                raise models._Cancelled()

    seen = []
    ok = models.download(e, progress=lambda d, t: None,
                         cancel=lambda: bool(seen.append(1)) or len(seen) > 2,  # stop after a couple
                         _fetch=fake_fetch)
    assert ok is False and not e.present                 # aborted, file not materialized


def test_cancel_active_cancels_daemon_job(monkeypatch):
    from peakstone.dashboard.app import Dashboard
    from peakstone.dashboard import client
    cancelled = []
    monkeypatch.setattr(client, "cancel_job", lambda jid, **k: cancelled.append(jid) or True)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test():
            assert app.cancel_active() is False               # nothing being mirrored
            app.run_active = True
            app._run_job_id = "job7"
            assert app.cancel_active() is True
            assert app._run_cancelled and cancelled == ["job7"]   # told the daemon to kill the run

    asyncio.run(scenario())


def test_quit_is_safe_runs_survive(monkeypatch):
    """Quitting the TUI never kills a run — the daemon owns it. action_quit just stops mirroring and
    exits (no confirm), and the run keeps going to be re-adopted next launch."""
    from peakstone.dashboard.app import Dashboard

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            exited = []
            monkeypatch.setattr(app, "exit", lambda *a, **k: exited.append(True))
            app.run_active = True
            app._run_job_id = "j"
            app.action_quit()
            await pilot.pause()
            assert exited == [True]
            assert app._run_cancelled                         # stops the local mirror only

    asyncio.run(scenario())


def test_queue_enter_opens_viewer():
    from peakstone.dashboard.app import Dashboard, QueueScreen, ReproduceScreen

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            app.run_active = True
            app._run_spec = {"name": "A", "level": "smoke", "challenge_ids": None,
                             "published_tps": None, "free_procs": None}
            await app.push_screen(QueueScreen())
            await pilot.pause()
            await pilot.press("enter")          # ⏎ on the active row opens the live run view
            await pilot.pause()
            assert isinstance(app.screen, ReproduceScreen)

    asyncio.run(scenario())


def test_run_auto_submits(monkeypatch):
    from peakstone.dashboard import history, client
    from peakstone.dashboard.app import Dashboard
    monkeypatch.setattr(history, "append", lambda e: None)
    # the daemon auto-submits; it reports that in the job summary. The TUI reflects it and refreshes.
    _stub_daemon(monkeypatch, summary={"submitted": True, "your_tps": 50.0})
    lb_calls = []
    monkeypatch.setattr(client, "get_leaderboard",
                        lambda *a, **k: lb_calls.append(1) or {"count": 0, "leaderboard": []})

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()           # initial mount load
            before = len(lb_calls)
            app.start_run("m")
            await app.workers.wait_for_complete()
            await pilot.pause()                             # let the post-submit refresh worker spawn
            await app.workers.wait_for_complete()
            assert app._run_submitted is True               # daemon-submitted state reflected
            assert len(lb_calls) > before                   # leaderboard refreshed to show the result

    asyncio.run(scenario())


def test_queue_screen_shows_daemon_queues(monkeypatch):
    """The QueueScreen reflects the daemon's queues: runs and (separately) downloads. x cancels the
    selected job; c clears all queued jobs. Everything is driven over the daemon client."""
    from peakstone.dashboard.app import Dashboard, QueueScreen
    from peakstone.dashboard import client
    from textual.widgets import DataTable

    jobs = [
        {"id": "b", "kind": "run", "status": "queued", "spec": {"model": "B", "ids": ["x", "y"]}, "created": 2},
        {"id": "c", "kind": "run", "status": "queued", "spec": {"model": "C", "level": "deep"}, "created": 3},
        {"id": "d", "kind": "download", "status": "queued", "spec": {"model": "D"}, "created": 4},
    ]

    def cancel(jid, **k):
        for j in jobs:
            if j["id"] == jid:
                j["status"] = "cancelled"
        return True

    monkeypatch.setattr(client, "list_jobs", lambda **k: [dict(j) for j in jobs])
    monkeypatch.setattr(client, "cancel_job", cancel)

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()        # on_mount refresh populates _daemon_jobs
            await app.push_screen(QueueScreen())
            await pilot.pause()
            t = app.screen.query_one("#q-tbl", DataTable)
            names = [str(t.get_row_at(i)[2]) for i in range(t.row_count)]
            assert names[:3] == ["B", "C", "D"]          # two queued runs, then the download queue

            t.move_cursor(row=0)                          # B
            await pilot.press("x")                        # cancel it on the daemon
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert next(j["status"] for j in jobs if j["id"] == "b") == "cancelled"

            await pilot.press("c")                        # clear all remaining queued (C + D)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert all(j["status"] == "cancelled" for j in jobs)

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
        from peakstone.dashboard.app import BoardTree
        app = Dashboard("http://down")
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            tree = app.query_one("#board", BoardTree)
            labels = [str(n.label) for n in tree.root.children]
            assert labels and "API unreachable" in labels[0]   # graceful, not a crash

    asyncio.run(scenario())


def test_model_says_label():
    from peakstone.dashboard.app import _model_says
    s = _model_says("qwen3-coder", "Q4_K_XL", 32768, "full")
    assert "qwen3-coder" in s and "Q4_K_XL" in s and "32K" in s and "think full" in s and "says:" in s
    assert _model_says("m").startswith("[b]<m>")          # minimal: just the name, no quant/ctx
    assert "?" not in _model_says("m", "?", None)          # unknown quant is dropped, not shown


def test_solution_screen_shows_prompt_thinking_and_label(monkeypatch):
    """The solution explorer now puts the system prompt in the top pane, the model's thinking before
    its answer in the bottom pane, and the <model · quant · ctx> says: line between them."""
    from peakstone.dashboard.app import Dashboard, SolutionScreen
    from textual.widgets import Static
    monkeypatch.setattr(client, "get_run_challenge", lambda url, bh, cid, **k: {
        "challenge": cid, "final": 1.0, "passed": 3, "total": 3,
        "transcript": {"system_prompt": "You are an expert coder.", "reasoning": "consider edge cases",
                       "raw_output": "def f(): pass", "stdout": "ok"}})

    async def scenario():
        app = Dashboard("http://x")
        async with app.run_test() as pilot:
            await pilot.pause()
            app.open_solution({"row": {"challenge": "py-05-calc"}, "bundle_hash": "bh1"},
                              {"family": "qz", "run": {"artifact": "Q6_K", "context": 32768}})
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, SolutionScreen)
            spec = str(app.screen.query_one("#sol-spec", Static).render())
            out = str(app.screen.query_one("#sol-out", Static).render())
            says = str(app.screen.query_one("#sol-says", Static).render())
            assert "system prompt" in spec and "You are an expert coder." in spec
            assert "thinking" in out and "consider edge cases" in out and "def f(): pass" in out
            assert "qz" in says and "Q6_K" in says and "32K" in says and "says:" in says

    asyncio.run(scenario())


def test_reproduce_says_label_and_phase_sections(monkeypatch):
    """The live run viewer shows the identity line above the output, and retains the per-challenge
    output sectioned into thinking / answer (from the streamed phase markers)."""
    from peakstone.dashboard.app import Dashboard, ReproduceScreen, GEN_MARK, GEN_PHASE
    from textual.widgets import Static
    monkeypatch.setattr(_models, "load_registry", lambda: {})   # 'm' not registered -> no quant, fine

    async def scenario():
        app = Dashboard("http://x")
        app._run_spec = {"name": "qwen3-coder", "ctx": 32768}
        app._daemon_jobs = []
        async with app.run_test() as pilot:
            scr = ReproduceScreen()
            await app.push_screen(scr)
            await pilot.pause()
            scr.reset_view()
            await pilot.pause()
            says = str(scr.query_one("#repro-says", Static).render())
            assert "qwen3-coder" in says and "32K" in says and "says:" in says
            # stream a challenge: solving -> thinking deltas -> answering deltas
            scr._on_line("   qwen3-coder | c1   → solving [tests] …")
            scr._on_line(GEN_PHASE + "thinking")
            scr._on_line(GEN_MARK + "let me think")
            scr._on_line(GEN_PHASE + "answering")
            scr._on_line(GEN_MARK + "def f(): pass")
            sol = scr._solutions["c1"]
            assert "── thinking ──" in sol and "let me think" in sol
            assert "── answer ──" in sol and "def f(): pass" in sol
            assert sol.index("── thinking ──") < sol.index("── answer ──")

    asyncio.run(scenario())


def test_solution_body_sections_retry_attempts():
    """When the transcript carries a self-repair sequence, the solution body shows each attempt's
    thinking + answer and the error fed back, in order."""
    from peakstone.dashboard.app import _solution_body
    body = _solution_body({"challenge": "c", "final": 1.0, "passed": 2, "total": 2, "transcript": {
        "attempts": [
            {"answer": "v1", "reasoning": "first idea", "passed": 1, "total": 2,
             "test_error": "AssertionError: nope"},
            {"answer": "v2", "reasoning": "fix it", "passed": 2, "total": 2, "test_error": ""},
        ]}})
    assert "attempt 1/2" in body and "attempt 2/2" in body
    assert "first idea" in body and "v1" in body and "AssertionError: nope" in body
    assert "error fed back" in body and "fix it" in body and "v2" in body
    assert body.index("attempt 1/2") < body.index("attempt 2/2")   # in order


def test_reproduce_attempt_boundary_in_review(monkeypatch):
    from peakstone.dashboard.app import Dashboard, ReproduceScreen, GEN_MARK, GEN_ATTEMPT
    monkeypatch.setattr(_models, "load_registry", lambda: {})

    async def scenario():
        app = Dashboard("http://x")
        app._run_spec = {"name": "m"}
        app._daemon_jobs = []
        async with app.run_test() as pilot:
            scr = ReproduceScreen()
            await app.push_screen(scr)
            await pilot.pause()
            scr.reset_view()
            scr._on_line("   m | c1   → solving [tests] …")
            scr._on_line(GEN_MARK + "first answer")
            scr._on_line(GEN_ATTEMPT + "2")               # a self-repair retry began
            scr._on_line(GEN_MARK + "second answer")
            sol = scr._solutions["c1"]
            assert "first answer" in sol and "attempt 2" in sol and "second answer" in sol
            assert sol.index("first answer") < sol.index("attempt 2") < sol.index("second answer")

    asyncio.run(scenario())

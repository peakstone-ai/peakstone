"""R8 — judge-LAST automation: a judge=true level run auto-queues a judge pass; the JUDGED bundle
is what gets submitted (the gen-only bundle wouldn't satisfy its own level definition)."""
from __future__ import annotations

import asyncio

from peakstone.gateway.jobs import JobManager, JobStore
from peakstone.gateway.tests.test_gateway import FakeProc, make_manager


def test_level_run_chains_judge_pass_and_submits_judged_bundle(monkeypatch, tmp_path):
    import peakstone.engine.serving as serving

    cmds: list[list[str]] = []

    def fake_stream(cmd, *, out, timeout, env_extra=None, log=lambda s: None, on_proc=None,
                    popen=None):
        on_proc and on_proc(FakeProc())
        cmds.append(cmd)
        return {"bundle_hash": f"h{len(cmds)}",
                "results": [{"verification": "deterministic-tests",
                             "score": {"final": 1.0, "passed": 3, "total": 3}, "tok_per_s": 50.0}]}

    monkeypatch.setattr(serving, "stream_runner", fake_stream)
    monkeypatch.setattr(serving, "level_needs_judge", lambda lv: lv == "standard")
    monkeypatch.setattr(serving, "judge_model_name", lambda: "model-b")
    submitted: list[dict] = []

    async def scenario():
        mgr = make_manager()
        store = JobStore(tmp_path / "jobs.db")
        jm = JobManager(store, mgr, gateway_url="http://x",
                        submit=lambda b: (submitted.append(b), (201, "ok"))[1],
                        present=lambda m: True)
        jm.start()
        jid = jm.enqueue({"model": "model-a", "level": "standard"})
        fid = None
        for _ in range(300):
            gen = store.get(jid)
            if gen["status"] == "done":
                fid = gen["summary"].get("judge_job")
                if fid and store.get(fid)["status"] in ("done", "failed"):
                    break
            await asyncio.sleep(0.02)
        gen = store.get(jid)
        assert gen["status"] == "done" and gen["summary"]["submitted"] is False   # deferred
        assert fid and store.get(fid)["status"] == "done"
        judge = store.get(fid)
        assert judge["spec"]["model"] == "model-b" and judge["spec"]["judge_of"] == jid
        # the second runner invocation is the judge pass over the gen outdir, bundling enabled
        assert len(cmds) == 2 and "--judge-only" in cmds[1] and "--bundle" in cmds[1]
        assert "--judge-model" in cmds[1] and cmds[1][cmds[1].index("--judge-model") + 1] == "model-b"
        # exactly ONE submission: the judged bundle, not the gen-only one
        assert [b["bundle_hash"] for b in submitted] == ["h2"]
        await jm.aclose()

    asyncio.run(scenario())


def test_non_judge_level_submits_directly(monkeypatch, tmp_path):
    import peakstone.engine.serving as serving
    from peakstone.gateway.tests.test_gateway import _fake_stream_ok

    monkeypatch.setattr(serving, "stream_runner", _fake_stream_ok)
    monkeypatch.setattr(serving, "level_needs_judge", lambda lv: False)
    submitted: list[dict] = []

    async def scenario():
        mgr = make_manager()
        store = JobStore(tmp_path / "jobs.db")
        jm = JobManager(store, mgr, gateway_url="http://x",
                        submit=lambda b: (submitted.append(b), (201, "ok"))[1],
                        present=lambda m: True)
        jm.start()
        jid = jm.enqueue({"model": "model-a", "ids": ["x"]})
        for _ in range(300):
            if store.get(jid)["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.02)
        gen = store.get(jid)
        assert gen["status"] == "done" and gen["summary"]["submitted"] is True
        assert "judge_job" not in gen["summary"] and len(submitted) == 1
        await jm.aclose()

    asyncio.run(scenario())

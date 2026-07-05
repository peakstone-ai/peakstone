"""localboard: scan, suite-scope + fallback, degraded results.json rows, jobs.db join, cache,
and the pure merge (dedupe/collapse/sort/rank)."""
from __future__ import annotations

import json

import pytest

from peakstone.dashboard import localboard as lb


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch, tmp_path):
    """Isolate the module-level cache + point the cache file at a tmp home per test."""
    lb._mem = None
    monkeypatch.setattr(lb.paths, "home_dir", lambda: tmp_path / "home")
    yield
    lb._mem = None


def _write_bundle(d, *, family, artifact="Q4", results, suite="level-standard@2026.08",
                  bundle_hash="h", release_date=None, reasoning=None):
    d.mkdir(parents=True, exist_ok=True)
    sid, _, ver = suite.partition("@")
    (d / "bundle.json").write_text(json.dumps({
        "bundle_hash": bundle_hash, "submitted_at": "2026-07-05T00:00:00Z",
        "model": {"family": family, "artifact": artifact, "release_date": release_date,
                  "reasoning": reasoning, "serve_flags": "-ngl 99", "context": 32768,
                  "engine": {"name": "llama.cpp"}},
        "environment": {"gpu": "RTX 4090", "vram_gb": 24},
        "suite": {"id": sid, "version": ver, "content_hash": "x"},
        "results": results}))


def _res(cid, final, category="basic", verification="deterministic-tests"):
    return {"challenge_id": cid, "category": category, "verification": verification,
            "score": {"final": final, "passed": int(final), "total": 1}}


def test_scan_and_default_suite_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "default_suite", lambda: "level-standard@2026.08")
    root = tmp_path / "results"
    _write_bundle(root / "run-a", family="m1", results=[_res("c1", 1.0), _res("c2", 0.0)])
    _write_bundle(root / "seed" / "m2", family="m2", suite="level-quick@2026.08",
                  results=[_res("c1", 1.0)], bundle_hash="h2")   # different suite

    rows, scoped = lb.build_local_board(root=root)
    assert scoped and {r["family"] for r in rows} == {"m1"}      # quick run filtered out
    assert rows[0]["code_score"] == 0.5 and rows[0]["run"]["local"] is True

    allrows, scoped2 = lb.build_local_board(root=root, all_suites=True)
    assert not scoped2 and {r["family"] for r in allrows} == {"m1", "m2"}


def test_empty_scope_falls_back_to_all(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "default_suite", lambda: "level-standard@9999.99")  # matches nothing
    root = tmp_path / "results"
    _write_bundle(root / "run-a", family="m1", results=[_res("c1", 1.0)])
    rows, scoped = lb.build_local_board(root=root)
    assert not scoped and len(rows) == 1     # never render an empty board when runs exist


def test_missing_root_is_empty(tmp_path):
    rows, scoped = lb.build_local_board(root=tmp_path / "nope")
    assert rows == [] and scoped is True


def test_corrupt_bundle_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "default_suite", lambda: "level-standard@2026.08")
    root = tmp_path / "results"
    _write_bundle(root / "good", family="ok", results=[_res("c1", 1.0)])
    bad = root / "bad"; bad.mkdir(parents=True)
    (bad / "bundle.json").write_text("{not json")
    rows, _ = lb.build_local_board(root=root)
    assert {r["family"] for r in rows} == {"ok"}


def test_results_json_only_degraded_row(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "default_suite", lambda: "level-standard@2026.08")
    root = tmp_path / "results"
    d = root / "smoke"; d.mkdir(parents=True)
    (d / "results.json").write_text(json.dumps({
        "meta": {"models": ["mini"], "suite_id": "level-standard", "suite_version": "2026.08"},
        "results": [{"challenge": "c1", "type": "basic", "scoring": "tests",
                     "final_score": 1.0, "passed": 1, "total": 1}]}))
    rows, _ = lb.build_local_board(root=root)
    assert len(rows) == 1
    assert rows[0]["family"] == "mini" and rows[0]["run"]["artifact"] == "(no bundle)"
    assert rows[0]["run"]["no_bundle"] and rows[0]["run"]["bundle_hash"] is None
    assert rows[0]["code_score"] == 1.0


def test_submitted_join_from_jobs_db(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "default_suite", lambda: "level-standard@2026.08")
    root = tmp_path / "results"
    _write_bundle(root / "run-a", family="m1", results=[_res("c1", 1.0)], bundle_hash="HASH1")
    monkeypatch.setattr(lb.paths, "repo_root", lambda: tmp_path)
    from peakstone.gateway.jobs import JobStore
    store = JobStore(tmp_path / "results" / "jobs.db")
    jid = store.enqueue({"model": "m1"}, now=0.0)
    store.update(jid, status="done", summary={"bundle_hash": "HASH1", "submitted": True})
    rows, _ = lb.build_local_board(root=root)
    assert rows[0]["run"]["submitted"] is True


def test_cache_hit_avoids_reparse(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "default_suite", lambda: "level-standard@2026.08")
    monkeypatch.setattr(lb.paths, "repo_root", lambda: tmp_path)   # no real jobs.db in the count
    root = tmp_path / "results"
    _write_bundle(root / "run-a", family="m1", results=[_res("c1", 1.0)])
    reads = {"bundle": 0}
    real_rt = lb.Path.read_text
    def counting_rt(self, *a, **k):
        if self.name == "bundle.json":
            reads["bundle"] += 1
        return real_rt(self, *a, **k)
    monkeypatch.setattr(lb.Path, "read_text", counting_rt)
    lb.build_local_board(root=root)
    assert reads["bundle"] == 1          # parsed once
    lb._mem = None                       # drop in-memory; force file-cache reload
    lb.build_local_board(root=root)
    assert reads["bundle"] == 1          # cache hit → the bundle was NOT re-read


def test_cache_version_invalidates(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "default_suite", lambda: "level-standard@2026.08")
    root = tmp_path / "results"
    _write_bundle(root / "run-a", family="m1", results=[_res("c1", 1.0)])
    lb.build_local_board(root=root)
    cache_file = (tmp_path / "home" / "localboard_cache.json")
    stale = json.loads(cache_file.read_text()); stale["version"] = -1
    cache_file.write_text(json.dumps(stale))
    lb._mem = None
    assert lb._load_cache()["version"] == lb.CACHE_VERSION   # stale version dropped


# --------------------------------------------------------------------------- merge

def _row(family, artifact="Q4", *, n_total=10, code=0.5, held_out=None, status="provisional",
         bundle_hash=None, local=True, reasoning=None):
    return {"family": family, "held_out_status": status, "held_out_score": held_out,
            "code_score": code, "n_total": n_total,
            "run": {"artifact": artifact, "reasoning": reasoning, "reasoning_budget": None,
                    "bundle_hash": bundle_hash, "local": local}}


def test_merge_dedupes_published():
    local = [_row("m1", bundle_hash="H", code=0.5)]
    server = [_row("m1", bundle_hash="H", code=0.5, local=False, status="ranked", held_out=0.9)]
    merged = lb.merge_rows(local, server, sort="held_out_score")
    assert len(merged) == 1
    assert merged[0]["run"]["published"] and merged[0]["run"]["submitted"]


def test_merge_collapse_keeps_higher_coverage():
    a = _row("m1", n_total=5, code=0.9)
    b = _row("m1", n_total=20, code=0.4)     # same quant key, more coverage → wins
    merged = lb.merge_rows([a, b], [], sort="code_score")
    assert len(merged) == 1 and merged[0]["n_total"] == 20


def test_merge_held_out_two_tier_order():
    ranked = _row("srv", status="ranked", held_out=0.8, local=False, bundle_hash="s")
    prov = _row("loc", status="provisional", code=0.95, bundle_hash="l")
    merged = lb.merge_rows([prov], [ranked], sort="held_out_score")
    assert [r["family"] for r in merged] == ["srv", "loc"]   # ranked first, then provisional
    assert [r["rank"] for r in merged] == [1, 2]


def test_merge_axis_drops_value_less_rows():
    have = _row("a", bundle_hash="a"); have["agent_score"] = 0.7
    none = _row("b", bundle_hash="b")   # no agent_score key
    merged = lb.merge_rows([have, none], [], sort="agent_score")
    assert [r["family"] for r in merged] == ["a"]


def test_read_run_results(tmp_path):
    root = tmp_path / "results"
    _write_bundle(root / "run-a", family="m1",
                  results=[_res("c1", 1.0), _res("c2", 0.0)])
    out = lb.read_run_results(str(root / "run-a"))
    assert [r["challenge"] for r in out] == ["c2", "c1"]   # failures first
    assert out[0]["final"] == 0.0
    assert lb.read_run_results(str(tmp_path / "nope")) is None

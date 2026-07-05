"""`peakstone check` — the CI regression gate: axis math, gating policy, comparability rules."""
from __future__ import annotations

import json

from peakstone.engine.check import check_main, compare

SUITE = {"id": "level-standard", "version": "2026.08", "content_hash": "abc"}


def _row(cid, final, category="basic", verification="deterministic-tests", chash=None):
    return {"challenge_id": cid, "challenge_hash": chash or f"h-{cid}",
            "category": category, "verification": verification,
            "score": {"final": final, "passed": int(final), "total": 1}}


def _bundle(rows, suite=None, sha="f" * 64):
    return {"suite": dict(suite or SUITE),
            "model": {"family": "m", "artifact": "Q4", "file_sha256": sha},
            "results": rows}


def _corpus(score_by_cat: dict[str, list[float]]):
    rows = []
    for cat, finals in score_by_cat.items():
        for i, f in enumerate(finals):
            verification = "goal-state-env" if cat == "env" else "deterministic-tests"
            rows.append(_row(f"{cat}-{i}", f, category=("basic" if cat == "env" else cat),
                             verification=verification))
    return rows


def test_identical_runs_pass():
    b = _bundle(_corpus({"basic": [1, 1, 0, 1, 1], "math": [1, 0, 1, 1, 1]}))
    v = compare(b, b, max_drop=0.02, min_n=5)
    assert v["comparable"] and v["ok"] and v["regressed"] == []
    assert v["axes"]["code"]["delta"] == 0.0


def test_axis_drop_beyond_threshold_fails():
    base = _bundle(_corpus({"basic": [1, 1, 1, 1, 1]}))
    cur = _bundle(_corpus({"basic": [1, 1, 1, 0, 0]}))   # 1.0 -> 0.6
    v = compare(cur, base, max_drop=0.02, min_n=5)
    assert not v["ok"] and v["regressed"] == ["code"]
    assert v["axes"]["code"]["delta"] == -0.4


def test_small_axis_reported_but_not_gated():
    base = _bundle(_corpus({"basic": [1] * 5, "math": [1, 1]}))
    cur = _bundle(_corpus({"basic": [1] * 5, "math": [0, 0]}))   # math collapsed, but n=2 < min_n
    v = compare(cur, base, max_drop=0.02, min_n=5)
    assert v["ok"]
    assert v["axes"]["math"]["delta"] == -1.0 and not v["axes"]["math"]["gated"]


def test_axes_split_mirrors_board():
    rows = _corpus({"basic": [1.0], "math": [0.5], "long-context": [0.25],
                    "injection": [1.0], "env": [1.0], "planner": [0.75]})
    v = compare(_bundle(rows), _bundle(rows), max_drop=0.02, min_n=1)
    got = {k: a["current"] for k, a in v["axes"].items()}
    assert got == {"code": 1.0, "math": 0.5, "long-context": 0.25,
                   "safety": 1.0, "agentic": 1.0, "planner": 0.75}


def test_flips_listed():
    base = _bundle(_corpus({"basic": [1, 0, 1, 1, 1]}))
    cur = _bundle(_corpus({"basic": [1, 1, 0, 1, 1]}))
    v = compare(cur, base, max_drop=1.0, min_n=5)   # wide threshold: flips only, no gate
    assert v["flips"] == {"fixed": ["basic-1"], "broke": ["basic-2"]}


def test_different_suite_not_comparable():
    v = compare(_bundle(_corpus({"basic": [1] * 5})),
                _bundle(_corpus({"basic": [1] * 5}), suite={**SUITE, "version": "2026.07"}),
                max_drop=0.02, min_n=5)
    assert not v["comparable"] and "different suites" in v["reason"]


def test_content_hash_mismatch_refused_unless_relaxed():
    base = _bundle(_corpus({"basic": [1] * 5}), suite={**SUITE, "content_hash": "other"})
    cur = _bundle(_corpus({"basic": [1] * 5}) + [_row("basic-9", 0.0)])
    v = compare(cur, base, max_drop=0.02, min_n=5)
    assert not v["comparable"] and "content_hash" in v["reason"]
    # relaxed: compares the shared, content-identical ids only (basic-9 exists on one side)
    v = compare(cur, base, max_drop=0.02, min_n=5, relax=True)
    assert v["comparable"] and v["ok"] and v["suite"]["n_compared"] == 5


def test_relax_drops_edited_challenges():
    # same id but different challenge content -> not the same measurement -> excluded
    base = _bundle([_row("a", 1.0), _row("b", 1.0, chash="h-old")],
                   suite={**SUITE, "content_hash": "x"})
    cur = _bundle([_row("a", 1.0), _row("b", 0.0, chash="h-new")],
                  suite={**SUITE, "content_hash": "y"})
    v = compare(cur, base, max_drop=0.02, min_n=1, relax=True)
    assert v["suite"]["n_compared"] == 1 and v["ok"]   # 'b' excluded, so no regression


def test_gate_categories_opt_in():
    base = _bundle(_corpus({"basic": [1] * 5, "go": [1] * 5}))
    cur = _bundle(_corpus({"basic": [1] * 5, "go": [0] * 5}))
    # both are code-axis rows; code = 10 -> 5 solved = -0.5 -> already gates. Narrow the check:
    v = compare(cur, base, max_drop=0.6, min_n=5)             # axis delta -0.5 passes at 0.6
    assert v["ok"]
    v = compare(cur, base, max_drop=0.6, min_n=5, gate_categories=True)
    assert not v["ok"] and v["regressed"] == ["category:go"]  # the per-category gate catches it


def test_cli_exit_codes(tmp_path):
    ok = _bundle(_corpus({"basic": [1] * 5}))
    bad = _bundle(_corpus({"basic": [0] * 5}))
    (tmp_path / "base.json").write_text(json.dumps(ok))
    (tmp_path / "cur.json").write_text(json.dumps(bad))
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "bundle.json").write_text(json.dumps(ok))
    a = str(tmp_path / "base.json")
    assert check_main([a, "--against", a]) == 0
    assert check_main([str(tmp_path / "cur.json"), "--against", a]) == 1
    assert check_main([str(tmp_path / "run"), "--against", a]) == 0      # run-dir form
    assert check_main([str(tmp_path / "nope.json"), "--against", a]) == 2

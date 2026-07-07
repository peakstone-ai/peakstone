"""R8 — the judge-LAST pass re-emits a signed bundle that (a) keeps the GENERATION run's identity
(suite, budget) and (b) records the judge model + sampling params as part of the run record."""
from __future__ import annotations

import json
from types import SimpleNamespace

from peakstone.engine import runner
from peakstone.engine.judge import JUDGE_MAX_TOKENS, JUDGE_TEMPERATURE

RESPONSE = "```python\ndef f():\n    return 1\n```"


class FakeJudgeClient:
    def health(self):
        return True


def _gen_run(tmp_path):
    """A finished generation run dir: results.json with the original meta + one 'both' row."""
    meta = {"timestamp": "20260701-000000", "models": ["bench-m"], "judge": None,
            "gpu": None, "mem_used": {}, "max_tokens": 8192, "max_tokens_reasoning": 8192,
            "suite_id": "level-standard", "suite_version": "2026.08"}
    rows = [{"model": "bench-m", "challenge": "py-01-x", "language": "python", "difficulty": 2,
             "category": "code", "type": "code", "scoring": "both",
             "final_score": 0.5, "test_score": 0.5, "passed": 5, "total": 10,
             "response": RESPONSE, "stdout": ""}]
    src = tmp_path / "gen-run"
    src.mkdir()
    (src / "results.json").write_text(json.dumps({"meta": meta, "results": rows}))
    return src


def test_judge_only_bundle_keeps_gen_identity_and_records_judge(tmp_path, monkeypatch):
    ch = SimpleNamespace(id="py-01-x", solution_file="main.py", language="python",
                         scoring="both", judge_weight=0.3, judge_criteria=["correctness"],
                         spec="do the thing")
    monkeypatch.setattr(runner, "load_challenges", lambda d: [ch])
    monkeypatch.setattr(runner, "judge_solution",
                        lambda *a, **k: {"scores": {"correctness": 9}, "normalized": 0.9})
    src = _gen_run(tmp_path)
    out = tmp_path / "judged"
    args = SimpleNamespace(judge_only=str(src), challenges_dir="challenges", out=str(out),
                           bundle=True, lang=None, difficulty=None, ids=None, models=None)
    assert runner.run_judge_only(args, "judge-36-moe", FakeJudgeClient()) == 0

    b = json.loads((out / "bundle.json").read_text())
    # (a) the GENERATION run's identity survives: suite + the budget it actually ran at
    assert b["suite"]["id"] == "level-standard" and b["suite"]["version"] == "2026.08"
    assert b["model"]["sampling"]["max_tokens"] == 8192
    # (b) the judge is part of the record: model + sampling params on the judged row
    row = b["results"][0]
    assert row["judge"]["model"] == "judge-36-moe"
    assert row["judge"]["temperature"] == JUDGE_TEMPERATURE
    assert row["judge"]["max_tokens"] == JUDGE_MAX_TOKENS
    # and the score was re-folded: 0.7*test + 0.3*judge
    assert row["score"]["final"] == round(0.7 * 0.5 + 0.3 * 0.9, 3)


def test_judge_only_bundle_refuses_multi_model_dirs(tmp_path, monkeypatch):
    ch = SimpleNamespace(id="py-01-x", solution_file="main.py", language="python",
                         scoring="both", judge_weight=0.3, judge_criteria=["c"], spec="s")
    monkeypatch.setattr(runner, "load_challenges", lambda d: [ch])
    monkeypatch.setattr(runner, "judge_solution",
                        lambda *a, **k: {"scores": {"c": 5}, "normalized": 0.5})
    src = _gen_run(tmp_path)
    data = json.loads((src / "results.json").read_text())
    data["results"].append({**data["results"][0], "model": "other-m"})
    (src / "results.json").write_text(json.dumps(data))
    args = SimpleNamespace(judge_only=str(src), challenges_dir="challenges",
                           out=str(tmp_path / "j2"), bundle=True,
                           lang=None, difficulty=None, ids=None, models=None)
    assert runner.run_judge_only(args, "judge-36-moe", FakeJudgeClient()) == 1   # refuse: one model per bundle
    assert not (tmp_path / "j2" / "bundle.json").exists()

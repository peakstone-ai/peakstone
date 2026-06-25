"""Test-level manifest loading + deterministic resolution."""
from __future__ import annotations

from pathlib import Path

from peakstone.engine.challenges import Challenge
from peakstone.engine.levels import Level, load_levels, resolve


def _ch(cid, family, difficulty=1):
    return Challenge(id=cid, title=cid, language="python", difficulty=difficulty, category="x",
                     scoring="tests", solution_file="solution.py", timeout=30,
                     dir=Path(f"challenges/{family}/{cid}"), spec="")


CORPUS = (
    [_ch(f"he-{i:03d}", "humaneval") for i in range(5)]
    + [_ch(f"py-{i}", "python", difficulty=(1 if i < 3 else 4)) for i in range(5)]
    + [_ch(f"aime-{i}", "aime") for i in range(3)]
)


def test_load_levels_manifest():
    version, levels = load_levels()
    assert version and {"smoke", "quick", "standard", "deep", "max"} <= set(levels)
    assert levels["standard"].judge is True
    assert levels["deep"].agent and levels["deep"].prebuilt
    assert levels["smoke"].judge is False


def test_resolve_caps_filters_and_is_deterministic():
    level = Level("t", select=[
        {"family": "python", "difficulty": [1, 2], "limit": 3},
        {"family": "humaneval", "limit": 2},
    ])
    out = resolve(level, CORPUS)
    assert out == ["py-0", "py-1", "py-2", "he-000", "he-001"]   # python (diff 1) first, then humaneval
    assert resolve(level, CORPUS) == out                         # deterministic -> stable content_hash
    # difficulty filter excluded the diff-4 python challenges; cap respected
    assert all(not c for c in out if c.startswith("py-3") or c.startswith("py-4"))


def test_capabilities_and_relevance(tmp_path):
    from peakstone.engine.levels import GATED_CAP, model_capabilities, relevant
    reg = tmp_path / "models.toml"
    reg.write_text(
        '["full"]\nctx=200000\n\n'
        '["small"]\nctx=8192\n\n'                      # small ctx -> agentic inferred off
        '["restricted"]\nctx=200000\ncapabilities=["code","math"]\n')
    full = model_capabilities("full", reg)
    small = model_capabilities("small", reg)
    restricted = model_capabilities("restricted", reg)
    unknown = model_capabilities("ghost", reg)         # not in registry -> full
    assert "tools" in full and "agentic" in full and unknown == full
    assert "tools" in small and "agentic" not in small
    assert "tools" not in restricted and "agentic" not in restricted

    # baseline axes always attempted; gated axes follow capability
    for fam in ("livecodebench", "aime", "refusal"):
        assert relevant(fam, restricted) and relevant(fam, small)
    assert not relevant("tool-calling", restricted) and not relevant("swebench", restricted)
    assert relevant("tool-calling", small) and not relevant("swebench", small)   # tools yes, agentic no
    assert relevant("swebench", full) and relevant("tool-calling", full)
    assert GATED_CAP["swebench"] == "agentic"


def test_resolve_dedups_across_axes():
    level = Level("t", select=[{"family": "aime"}, {"family": "aime", "limit": 1}])
    out = resolve(level, CORPUS)
    assert out == ["aime-0", "aime-1", "aime-2"] and len(out) == len(set(out))

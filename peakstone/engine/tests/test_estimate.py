"""Level cost estimate: bucketing, totals, and unknown-calibration handling."""
from __future__ import annotations

from pathlib import Path

from peakstone.engine import estimate as est
from peakstone.engine.challenges import Challenge


def _ch(cid, family, difficulty=1):
    return Challenge(id=cid, title=cid, language="python", difficulty=difficulty, category="x",
                     scoring="tests", solution_file="solution.py", timeout=30,
                     dir=Path(f"challenges/{family}/{cid}"), spec="")


_CORPUS = ([_ch(f"he-{i}", "humaneval") for i in range(3)]
           + [_ch(f"aime-{i}", "aime") for i in range(2)]
           + [_ch("tool-0", "tool-calling")])


def _patch(monkeypatch, *, tps, mbps, caps):
    monkeypatch.setattr(est, "load_challenges", lambda d: _CORPUS)
    monkeypatch.setattr(est.capabilities, "effective_capabilities", lambda m, **k: caps)
    monkeypatch.setattr(est, "_last_tps", lambda m: tps)
    monkeypatch.setattr(est.bandwidth, "estimated_mbps", lambda: mbps)


def test_estimate_known(monkeypatch):
    _patch(monkeypatch, tps=100.0, mbps=100.0, caps={"tools", "agentic", "reasoner"})
    e = est.estimate("quick", "m")
    assert e["tps"] == 100.0 and e["n_challenges"] == 6
    assert set(e["by_family"]) == {"humaneval", "aime", "tool-calling"}
    assert e["total_min"] >= e["gen_min"] > 0
    assert e["unknowns"] == []                       # tps + bandwidth known
    assert "quick" in est.format_estimate(e)


def test_estimate_relevance_drops_axes(monkeypatch):
    _patch(monkeypatch, tps=100.0, mbps=100.0, caps={"reasoner"})   # no tools
    e = est.estimate("quick", "m")
    assert "tool-calling" not in e["by_family"]      # gated out for a no-tools model


def test_estimate_unknown_tps(monkeypatch):
    _patch(monkeypatch, tps=None, mbps=None, caps={"tools", "agentic"})
    e = est.estimate("quick", "m")
    assert e["tps"] is None and any("tps" in u for u in e["unknowns"])

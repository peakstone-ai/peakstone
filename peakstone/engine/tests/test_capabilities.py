"""Capability cache precedence, observe mapping, and probe/classify with a stub client."""
from __future__ import annotations

import json

from peakstone.engine import capabilities as cap
from peakstone.engine.provider import ChatResult


def _reg(tmp_path, body):
    p = tmp_path / "models.toml"
    p.write_text(body)
    return p


def test_effective_precedence(tmp_path):
    reg = _reg(tmp_path, '["big"]\nctx=200000\n\n["small"]\nctx=8192\n\n["decl"]\nctx=200000\ncapabilities=["code"]\n')
    cache = tmp_path / "cap.json"
    eff = lambda m: cap.effective_capabilities(m, models_toml=reg, cache_path=cache)

    assert eff("big") == {"tools", "agentic", "long_ctx"}      # inferred from big ctx
    assert eff("small") == {"tools"}                            # small ctx -> no agentic/long_ctx
    assert eff("decl") == {"long_ctx"}                          # declared ["code"] -> no tools/agentic

    cap.update_cache("big", {"tools": False, "reasoner": True}, "probed", path=cache)
    assert eff("big") == {"agentic", "long_ctx", "reasoner"}    # cache overrides tools->false, adds reasoner
    # declared still beats the cache
    cap.update_cache("decl", {"tools": True}, "probed", path=cache)
    assert "tools" not in eff("decl")


def test_observe_mapping():
    rows = [
        {"category": "tool-calling", "final_score": 0.5},
        {"verification": "goal-state-env", "final_score": 1.0},
        {"category": "math", "final_score": 1.0},
        {"category": "code-correctness", "final_score": 1.0},   # not a capability signal
        {"category": "tool-calling", "final_score": 0.0},       # no engagement -> nothing
    ]
    assert cap.observe(rows) == {"tools": True, "agentic": True, "reasoner": True}
    # bundle-shaped (nested score) via key args
    bundle_rows = [{"category": "tool-calling", "score_final": 0.9}]
    assert cap.observe(bundle_rows, score_key="score_final") == {"tools": True}


def test_cache_roundtrip(tmp_path):
    c = tmp_path / "cap.json"
    cap.update_cache("m", {"tools": True}, "probed", path=c)
    cap.update_cache("m", {"agentic": False}, "observed", path=c)
    data = json.loads(c.read_text())
    assert data["m"]["caps"] == {"tools": True, "agentic": False} and data["m"]["source"] == "observed"


class _StubClient:
    def __init__(self, tool_calls=True, answer="204"):
        self._tool = tool_calls
        self._ans = answer

    def chat_tools(self, model, messages, tools, **kw):
        if self._tool:
            return {"message": {"tool_calls": [{"id": "1", "function": {"name": "calc", "arguments": "{}"}}]},
                    "error": None}
        return {"message": {"content": "23*19 = 437"}, "error": None}   # answered without a tool call

    def chat(self, model, messages, **kw):
        return ChatResult(text=f"... \\boxed{{{self._ans}}}", reasoning="", error=None)


def test_probe_tools_and_classify(tmp_path):
    c = tmp_path / "cap.json"
    assert cap.probe_tools(_StubClient(tool_calls=True), "m", {}) is True
    assert cap.probe_tools(_StubClient(tool_calls=False), "m", {}) is False
    assert cap.probe_reasoner(_StubClient(answer="204"), "m", {}) is True   # matches the probe's answer

    caps = cap.classify("m", _StubClient(tool_calls=True), {}, docker=False, cache_path=c)
    assert caps["tools"] is True and caps["reasoner"] is True and "agentic" not in caps  # docker off
    assert json.loads(c.read_text())["m"]["caps"]["tools"] is True


def test_multimodal_is_stub():
    assert cap.probe_multimodal(_StubClient(), "m", {}) is None

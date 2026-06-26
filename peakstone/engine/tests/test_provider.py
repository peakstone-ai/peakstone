"""Provider streaming: chat(on_delta=…) parses SSE and forwards generation deltas live."""
from __future__ import annotations

from peakstone.engine import provider


class _FakeSSE:
    """Stand-in for urlopen()'s response: iterates raw SSE byte lines."""
    def __init__(self, lines):
        self._lines = [ln.encode() for ln in lines]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


def test_chat_streams_deltas(monkeypatch):
    def chunk(content=None, reasoning=None, usage=None):
        delta = {}
        if content is not None:
            delta["content"] = content
        if reasoning is not None:
            delta["reasoning_content"] = reasoning
        body = {"choices": [{"delta": delta}]}
        if usage:
            body["usage"] = usage
        import json
        return f"data: {json.dumps(body)}\n"

    lines = [
        chunk(reasoning="think"),                              # reasoning streams too
        chunk(content="def f():"),
        chunk(content=" return 1\n"),
        chunk(usage={"prompt_tokens": 5, "completion_tokens": 7}),
        "data: [DONE]\n",
    ]
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda req, timeout=600: _FakeSSE(lines))

    got = []
    c = provider.LLMClient("http://x")
    c.on_delta = got.append                       # instance-level callback -> streaming path
    res = c.chat("m", [{"role": "user", "content": "hi"}])

    assert res.error is None
    assert res.text == "def f(): return 1\n"       # content accumulated, reasoning kept separate
    assert res.reasoning == "think"
    assert res.completion_tokens == 7
    assert "".join(got) == "thinkdef f(): return 1\n"   # every delta reached the consumer live


def test_chat_non_streaming_default(monkeypatch):
    import json

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}],
                               "usage": {"completion_tokens": 1}}).encode()

    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda req, timeout=600: _Resp())
    res = provider.LLMClient("http://x").chat("m", [{"role": "user", "content": "hi"}])
    assert res.text == "hello" and res.error is None

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


def test_is_looping():
    from peakstone.engine.provider import is_looping
    assert is_looping("the " * 80)                 # a word repeated
    assert is_looping("\n" * 300)                   # whitespace flood
    assert is_looping("ab" * 150)                   # tiny period
    assert not is_looping("def f():\n    return 1\n" * 2)        # short, not a long exact run
    assert not is_looping("a normal varied answer with no long exact repetition at all, really.")


def test_chat_stream_aborts_on_repetition(monkeypatch):
    import json
    from peakstone.engine import provider

    def chunk(c):
        return f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n"

    lines = [chunk("loop ") for _ in range(200)] + ["data: [DONE]\n"]   # a model stuck repeating
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda req, timeout=600: _FakeSSE(lines))
    got = []
    c = provider.LLMClient("http://x")
    c.on_delta = got.append
    res = c.chat("m", [{"role": "user", "content": "hi"}])

    assert res.aborted is True
    assert "repetition loop" in "".join(got)         # surfaced to the live view
    assert res.text.count("loop ") < 200             # bailed early instead of consuming the whole stream


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

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


def test_chat_stream_captures_finish_reason_and_truncation(monkeypatch):
    import json

    def chunk(content=None, finish_reason=None, usage=None):
        choice = {"delta": ({"content": content} if content is not None else {})}
        if finish_reason is not None:
            choice["finish_reason"] = finish_reason
        body = {"choices": [choice]}
        if usage:
            body["usage"] = usage
        return f"data: {json.dumps(body)}\n"

    # a generation that ran into the token budget: the last content chunk carries finish_reason=length
    lines = [chunk(content="def f(): # reasoning..."),
             chunk(content=" still thinking", finish_reason="length"),
             chunk(usage={"prompt_tokens": 5, "completion_tokens": 16384}),
             "data: [DONE]\n"]
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda req, timeout=600: _FakeSSE(lines))
    c = provider.LLMClient("http://x")
    c.stream = True
    res = c.chat("m", [{"role": "user", "content": "hi"}])
    assert res.finish_reason == "length" and res.truncated is True

    # a generation that stopped on its own is NOT truncated
    ok = [chunk(content="done", finish_reason="stop"), "data: [DONE]\n"]
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda req, timeout=600: _FakeSSE(ok))
    res2 = c.chat("m", [{"role": "user", "content": "hi"}])
    assert res2.finish_reason == "stop" and res2.truncated is False


def test_chat_stream_reports_thinking_then_answering_phase(monkeypatch):
    import json

    def chunk(content=None, reasoning=None, finish_reason=None):
        delta = {}
        if content is not None:
            delta["content"] = content
        if reasoning is not None:
            delta["reasoning_content"] = reasoning
        choice = {"delta": delta}
        if finish_reason:
            choice["finish_reason"] = finish_reason
        return f"data: {json.dumps({'choices': [choice]})}\n"

    # thinks first (reasoning channel), then answers (content channel), then stops naturally
    lines = [chunk(reasoning="let me think"), chunk(reasoning=" more"),
             chunk(content="answer: 42", finish_reason="stop"), "data: [DONE]\n"]
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda req, timeout=600: _FakeSSE(lines))
    phases = []
    c = provider.LLMClient("http://x")
    c.stream = True
    c.on_phase = phases.append
    res = c.chat("m", [{"role": "user", "content": "hi"}])
    assert phases == ["thinking", "answering"]      # fires once per channel transition
    assert res.saw_content is True and res.truncated_phase is None

    # truncated while still thinking — never reached the answer (saw_content stays False)
    cut = [chunk(reasoning="thinking and thinking", finish_reason="length"), "data: [DONE]\n"]
    monkeypatch.setattr(provider.urllib.request, "urlopen", lambda req, timeout=600: _FakeSSE(cut))
    res2 = c.chat("m", [{"role": "user", "content": "hi"}])
    assert res2.truncated is True and res2.truncated_phase == "thinking"


def test_is_looping():
    from peakstone.engine.provider import is_looping
    assert is_looping("the " * 80)                 # a word repeated
    assert is_looping("\n" * 300)                   # whitespace flood
    assert is_looping("ab" * 150)                   # tiny period
    # long, block-level repetition (period well beyond the old 50-char cap)
    block = "".join(chr(48 + (i * i + i) % 75) for i in range(120))   # ~120-char non-periodic block
    assert is_looping(block * 5)                    # >=3 reps over >=400 chars
    assert is_looping(block * 9 + block[:60])       # partial trailing rep still caught
    assert not is_looping(block * 2)                # only 2 reps of a medium block -> not flagged
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

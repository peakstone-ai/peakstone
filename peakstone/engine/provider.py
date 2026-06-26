"""OpenAI-compatible chat client (stdlib only).

Works against llama-server's /v1/chat/completions. Also usable against any
OpenAI-compatible endpoint (incl. a remote one) by passing base_url + api_key.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class ChatResult:
    text: str
    reasoning: str = ""          # reasoning_content (chain-of-thought) when the server exposes it
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    tok_per_s: float = 0.0
    error: str | None = None
    aborted: bool = False        # generation cut short (e.g. a degenerate repetition loop)


def is_looping(tail: str, *, max_period: int = 50, min_reps: int = 6, min_span: int = 200) -> bool:
    """True if the end of the generated text is a short unit repeated over and over — the degenerate
    loop low-bit quants fall into. Requires a long run of EXACT repetition (>= min_span chars, the
    smallest period repeated >= min_reps times) so normal repetitive code doesn't trip it."""
    n = len(tail)
    if n < min_span:
        return False
    for p in range(1, max_period + 1):
        unit = tail[n - p:]
        reps, i = 1, n - p
        while i - p >= 0 and tail[i - p:i] == unit:
            reps += 1
            i -= p
        if reps >= min_reps and reps * p >= min_span:
            return True
    return False


class LLMClient:
    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        # when set (callable taking a text delta), chat() streams and reports generation live;
        # the runner wires this up under --stream-output so the dashboard can show tokens as they land.
        self.on_delta = None

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: int = 600,
        on_delta=None,
    ) -> ChatResult:
        on_delta = on_delta or self.on_delta
        if on_delta is not None:
            return self._chat_stream(model, messages, temperature, max_tokens, timeout, on_delta)
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return ChatResult(text="", error=f"HTTP {e.code}: {e.read().decode()[:500]}")
        except Exception as e:  # noqa: BLE001
            return ChatResult(text="", error=f"{type(e).__name__}: {e}")
        dt = time.time() - t0

        try:
            msg = body["choices"][0]["message"]
            text = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""
        except (KeyError, IndexError):
            return ChatResult(text="", error=f"unexpected response: {str(body)[:400]}")
        usage = body.get("usage", {}) or {}
        ct = int(usage.get("completion_tokens", 0))
        tps = (ct / dt) if (dt > 0 and ct) else 0.0
        return ChatResult(
            text=text,
            reasoning=reasoning,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=ct,
            latency_s=round(dt, 2),
            tok_per_s=round(tps, 1),
        )

    def _chat_stream(self, model, messages, temperature, max_tokens, timeout, on_delta) -> ChatResult:
        """SSE streaming path: same result as chat(), but each content/reasoning delta is forwarded to
        on_delta as it arrives (batched ~48 chars to keep the consumer light). Used for live output."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "stream": True, "stream_options": {"include_usage": True}}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        text_parts, reason_parts, usage, pending = [], [], {}, []
        tail, since_check, aborted = "", 0, False   # for early repetition-loop detection

        def flush():
            if pending:
                on_delta("".join(pending))
                pending.clear()

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except ValueError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    delta = ((chunk.get("choices") or [{}])[0]).get("delta") or {}
                    piece = (delta.get("content") or "") + (delta.get("reasoning_content") or "")
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                    if delta.get("reasoning_content"):
                        reason_parts.append(delta["reasoning_content"])
                    if piece:
                        pending.append(piece)
                        if sum(len(p) for p in pending) >= 48 or "\n" in piece:
                            flush()
                        tail, since_check = (tail + piece)[-400:], since_check + len(piece)
                        if since_check >= 150:      # throttle the check; abort on a degenerate loop
                            since_check = 0
                            if is_looping(tail):
                                aborted = True
                                flush()
                                on_delta("\n⚠ aborted: repetition loop\n")
                                break               # closing the connection stops the server's generation
        except urllib.error.HTTPError as e:
            return ChatResult(text="", error=f"HTTP {e.code}: {e.read().decode()[:500]}")
        except Exception as e:  # noqa: BLE001
            return ChatResult(text="", error=f"{type(e).__name__}: {e}")
        flush()
        dt = time.time() - t0
        text, reasoning = "".join(text_parts), "".join(reason_parts)
        ct = int(usage.get("completion_tokens", 0))
        tps = (ct / dt) if (dt > 0 and ct) else 0.0
        return ChatResult(text=text, reasoning=reasoning,
                          prompt_tokens=int(usage.get("prompt_tokens", 0)), completion_tokens=ct,
                          latency_s=round(dt, 2), tok_per_s=round(tps, 1), aborted=aborted)

    def chat_tools(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout: int = 300,
        tool_choice: str = "auto",
    ) -> dict:
        """One turn of a tool-calling conversation. Returns
        {message, usage, latency_s, error}; message is the raw OpenAI assistant message
        (may contain `tool_calls`)."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model, "messages": messages, "tools": tools,
            "tool_choice": tool_choice, "temperature": temperature,
            "max_tokens": max_tokens, "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"message": None, "error": f"HTTP {e.code}: {e.read().decode()[:500]}"}
        except Exception as e:  # noqa: BLE001
            return {"message": None, "error": f"{type(e).__name__}: {e}"}
        try:
            msg = body["choices"][0]["message"]
        except (KeyError, IndexError):
            return {"message": None, "error": f"unexpected response: {str(body)[:400]}"}
        return {"message": msg, "usage": body.get("usage", {}) or {},
                "latency_s": round(time.time() - t0, 2), "error": None}

    def health(self, timeout: int = 5) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/v1/models", timeout=timeout) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001
            return False

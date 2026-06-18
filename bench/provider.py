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
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    tok_per_s: float = 0.0
    error: str | None = None


class LLMClient:
    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: int = 600,
    ) -> ChatResult:
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
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return ChatResult(text="", error=f"unexpected response: {str(body)[:400]}")
        usage = body.get("usage", {}) or {}
        ct = int(usage.get("completion_tokens", 0))
        tps = (ct / dt) if (dt > 0 and ct) else 0.0
        return ChatResult(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=ct,
            latency_s=round(dt, 2),
            tok_per_s=round(tps, 1),
        )

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

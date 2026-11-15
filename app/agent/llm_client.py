"""app/agent/llm_client.py — streaming chat client with automatic model fallback.

Groq and Mistral both speak the OpenAI chat-completions protocol, so one small
httpx client serves every provider. Models are tried in order (free Groq models
first, Mistral last). A model that answers 429/5xx/times out is put on a short
cooldown so the next message does not waste time on it, and the next model in
the chain takes over, as long as nothing has been streamed to the customer yet.

Secrets rule: API keys are unwrapped only in `_providers()`.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_COOLDOWN: dict[str, float] = {}      # model key -> monotonic time until which we skip it
DEFAULT_COOLDOWN = 45.0


class LLMUnavailableError(RuntimeError):
    """Every model in the chain failed."""


@dataclass
class Target:
    provider: str
    model: str
    base_url: str
    key: str

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"


def _providers() -> list[Target]:
    s = get_settings()
    targets: list[Target] = []
    if s.groq_api_key:
        key = s.groq_api_key.get_secret_value()
        for m in [x.strip() for x in s.agent_models.split(",") if x.strip()]:
            targets.append(Target("groq", m, "https://api.groq.com/openai/v1", key))
    if s.mistral_api_key:
        targets.append(Target("mistral", s.chat_model, "https://api.mistral.ai/v1",
                              s.mistral_api_key.get_secret_value()))
    return targets


def _extra_params(t: Target) -> dict[str, Any]:
    """Provider quirks: gpt-oss models are reasoning models; keep them quick and cheap."""
    if t.provider == "groq" and t.model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low"}
    return {}


async def stream_chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
) -> AsyncIterator[dict[str, Any]]:
    """Yield {"type": "delta", "text"} chunks, then one {"type": "done", ...}.

    `done` carries: model, tool_calls [{id, name, arguments(str)}], usage (total tokens).
    """
    targets = _providers()
    if not targets:
        raise LLMUnavailableError("No LLM key configured (set GROQ_API_KEY or MISTRAL_API_KEY)")

    last_error: Exception | None = None
    for t in targets:
        if _COOLDOWN.get(t.id, 0) > time.monotonic():
            continue
        for attempt in (1, 2):          # a model glitch (cooldown 0) gets one immediate retry
            emitted = False
            try:
                async for ev in _stream_one(t, messages, tools, temperature, max_tokens):
                    if ev["type"] == "delta":
                        emitted = True
                    yield ev
                return
            except _Retryable as exc:
                last_error = exc
                if emitted:
                    raise LLMUnavailableError(str(exc)) from exc   # part of an answer was already shown
                if exc.cooldown == 0 and attempt == 1:
                    logger.info("Model %s glitch (%s); retrying once", t.id, exc)
                    continue
                _COOLDOWN[t.id] = time.monotonic() + max(exc.cooldown, 2)
                logger.warning("Model %s unavailable (%s); cooling down %.0fs", t.id, exc, max(exc.cooldown, 2))
                break
    raise LLMUnavailableError(str(last_error or "all models are cooling down"))


class _Retryable(Exception):
    def __init__(self, msg: str, cooldown: float = DEFAULT_COOLDOWN):
        super().__init__(msg)
        self.cooldown = cooldown


async def _stream_one(t: Target, messages, tools, temperature, max_tokens) -> AsyncIterator[dict[str, Any]]:
    body: dict[str, Any] = {
        "model": t.model, "messages": messages, "stream": True,
        "temperature": temperature, "max_tokens": max_tokens, **_extra_params(t),
    }
    if t.provider == "groq":
        body["stream_options"] = {"include_usage": True}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    calls: dict[int, dict[str, str]] = {}
    text_buf = ""
    usage = 0
    timeout = httpx.Timeout(connect=8, read=40, write=10, pool=10)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{t.base_url}/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {t.key}"}) as resp:
                if resp.status_code == 429:
                    wait = _retry_after(resp)
                    raise _Retryable("rate limited", cooldown=min(max(wait, 2), 60))
                if resp.status_code >= 500 or resp.status_code in (408, 409):
                    raise _Retryable(f"HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "ignore")[:200]
                    # Bad request for this model (e.g. malformed tool call): try another one.
                    raise _Retryable(f"HTTP {resp.status_code} {detail}", cooldown=20)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("error"):
                        err = chunk["error"] if isinstance(chunk["error"], dict) else {}
                        code = str(err.get("code", ""))
                        # A malformed tool call is the model's glitch, not a quota problem: retry straight away.
                        raise _Retryable(f"stream error {code}", cooldown=0 if code == "tool_use_failed" else 15)
                    if chunk.get("usage"):
                        usage = chunk["usage"].get("total_tokens", usage)
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            text_buf += delta["content"]
                            yield {"type": "delta", "text": delta["content"]}
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["name"] = fn.get("name") or slot["name"]
                            slot["arguments"] += fn.get("arguments") or ""
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise _Retryable(f"network: {type(exc).__name__}", cooldown=20) from exc

    tool_calls = [calls[i] for i in sorted(calls) if calls[i]["name"]]
    if not tool_calls and text_buf:
        tool_calls = _parse_text_tool_calls(text_buf)
    if not tool_calls and not text_buf.strip():
        raise _Retryable("empty response", cooldown=0)
    yield {"type": "done", "model": t.id, "usage": usage, "tool_calls": tool_calls}


_TEXT_CALL = re.compile(r"<function=(\w+)>(.*?)</function>", re.S)
_TEXT_PARAM = re.compile(r"<parameter=(\w+)>\s*(.*?)\s*</parameter>", re.S)


def _parse_text_tool_calls(text: str) -> list[dict[str, str]]:
    """Some models (Qwen) write tool calls as <function=name><parameter=k>v</parameter></function> text."""
    out = []
    for i, (name, inner) in enumerate(_TEXT_CALL.findall(text)):
        args: dict[str, Any] = {}
        for k, v in _TEXT_PARAM.findall(inner):
            try:
                args[k] = json.loads(v)
            except json.JSONDecodeError:
                args[k] = v
        out.append({"id": f"text_{i}", "name": name, "arguments": json.dumps(args)})
    return out


def _retry_after(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("retry-after", "20"))
    except ValueError:
        return 20.0

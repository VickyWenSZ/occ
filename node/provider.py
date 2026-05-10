"""
LLM provider abstraction — Ollama (local) or OpenRouter (cloud).
Used only for user-facing inference (DeliberationEngine).
broker_agent.py always uses Ollama directly — never import this there.
"""
import json
import re
import uuid
from typing import Iterator

BUDGET_MODEL = "qwen/qwen3.5-9b"
STRONG_MODEL = "qwen/qwen3.5-35b-a3b"
_OR_BASE = "https://openrouter.ai/api/v1"
_STOP = ["<|endoftext|>", "<|im_start|>", "<|im_end|>"]


class _Fn:
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = arguments


class _TC:
    """Normalized tool call — duck-typed, compatible with engine iteration."""
    def __init__(self, tc_id: str, name: str, arguments: dict):
        self.id = tc_id
        self.function = _Fn(name, arguments)


class ProviderResponse:
    def __init__(
        self,
        content: str,
        tool_calls: list[_TC] | None,
        provider: str,
        hist_tcs=None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ):
        self.content = content
        self.tool_calls = tool_calls
        self._provider = provider
        self._hist_tcs = hist_tcs
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    def assistant_message(self) -> dict:
        return {"role": "assistant", "content": self.content, "tool_calls": self._hist_tcs}

    def tool_result(self, tc: _TC, result: str) -> dict:
        if self._provider == "openrouter":
            return {"role": "tool", "tool_call_id": tc.id, "content": result}
        return {"role": "tool", "content": result}


def call(
    messages: list,
    model_local: str,
    or_key: str,
    or_model: str,
    tools,
    temperature: float,
    num_ctx: int,
) -> ProviderResponse:
    """Non-streaming inference with optional tool support."""
    if or_key:
        return _or_call(messages, or_model, or_key, tools, temperature)
    return _ollama_call(messages, model_local, tools, temperature, num_ctx)


def stream(
    messages: list,
    model_local: str,
    or_key: str,
    or_model: str,
    temperature: float,
    num_ctx: int,
) -> Iterator[str]:
    """Streaming token generator (no tools)."""
    if or_key:
        yield from _or_stream(messages, or_model, or_key, temperature)
    else:
        yield from _ollama_stream(messages, model_local, temperature, num_ctx)


# ── OpenRouter ────────────────────────────────────────────────────────────────

def _extract_content(msg) -> str:
    """Extract visible text from an OR message, stripping <think> blocks.
    Falls back in order: reasoning_content → think block body → raw content."""
    raw = msg.content or ""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if cleaned:
        return cleaned
    # Some OR providers expose reasoning separately
    reasoning = getattr(msg, "reasoning_content", None) or ""
    if reasoning.strip():
        return reasoning.strip()
    # Model produced only a <think> block with no visible output (common with Qwen3
    # on analytical tasks like Critic). Use the think content rather than returning "".
    think_match = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
    if think_match:
        return think_match.group(1).strip()
    return raw.strip()

def _or_call(messages, model, api_key, tools, temperature) -> ProviderResponse:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=_OR_BASE, timeout=120.0)
    kw: dict = {"model": model, "messages": messages, "temperature": temperature, "stop": _STOP}
    if tools:
        kw["tools"] = tools
        kw["tool_choice"] = "auto"
    resp = client.chat.completions.create(**kw)
    msg = resp.choices[0].message
    content = _strip_leading_fragment(_extract_content(msg))
    raw_tcs = msg.tool_calls or []
    if not raw_tcs:
        return ProviderResponse(content, None, "openrouter")
    normalized = [
        _TC(
            tc.id,
            tc.function.name,
            json.loads(tc.function.arguments)
            if isinstance(tc.function.arguments, str)
            else (tc.function.arguments or {}),
        )
        for tc in raw_tcs
    ]
    hist = [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
        }
        for tc in raw_tcs
    ]
    return ProviderResponse(content, normalized, "openrouter", hist)


def _or_stream(messages, model, api_key, temperature) -> Iterator[str]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=_OR_BASE, timeout=120.0)
    in_think = False
    buf = ""
    header_stripped = False
    for chunk in client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, stop=_STOP, stream=True
    ):
        token = chunk.choices[0].delta.content or ""
        if not token:
            continue
        if in_think:
            if "</think>" in token:
                in_think = False
            continue
        buf += token
        if "<think>" in buf:
            in_think = True
            buf = ""
            continue
        # Strip a Qwen-leaked leading word fragment (e.g. "it. ", "dy. ") from
        # the very first emitted chunk. Only one strip per stream.
        if not header_stripped:
            if len(buf) >= 30 or "\n" in buf:
                buf = _strip_leading_fragment(buf)
                header_stripped = True
                if buf:
                    yield buf
                buf = ""
            continue
        # Normal flushing once the header is past
        if len(buf) > 20:
            yield buf
            buf = ""
    if buf and not in_think:
        if not header_stripped:
            buf = _strip_leading_fragment(buf)
        yield buf


# ── Ollama ────────────────────────────────────────────────────────────────────

_LEADING_FRAGMENT = re.compile(r'^[a-z]{1,8}\.\s+')


def _strip_leading_fragment(text: str) -> str:
    """Strip word-ending fragments that Qwen3 leaks before the actual response.
    Matches patterns like 'it. ', 'dy. ', 'ady. ' at the very start of content."""
    return _LEADING_FRAGMENT.sub("", text)


def _ollama_call(messages, model, tools, temperature, num_ctx) -> ProviderResponse:
    import ollama as _ollama
    response = _ollama.chat(
        model=model,
        messages=messages,
        tools=tools,
        think=False,
        keep_alive=-1,
        options={"temperature": temperature, "num_ctx": num_ctx, "stop": _STOP},
        stream=False,
    )
    msg = response.message
    content = _strip_leading_fragment(msg.content or "")
    raw_tcs = msg.tool_calls or []
    prompt_tokens = getattr(response, "prompt_eval_count", 0) or 0
    completion_tokens = getattr(response, "eval_count", 0) or 0
    if not raw_tcs:
        return ProviderResponse(content, None, "ollama", None, prompt_tokens, completion_tokens)
    normalized = [
        _TC(
            str(uuid.uuid4()),
            tc.function.name,
            tc.function.arguments if isinstance(tc.function.arguments, dict) else {},
        )
        for tc in raw_tcs
    ]
    return ProviderResponse(content, normalized, "ollama", raw_tcs, prompt_tokens, completion_tokens)


def _ollama_stream(messages, model, temperature, num_ctx) -> Iterator[str]:
    import ollama as _ollama
    buf = ""
    header_stripped = False
    for chunk in _ollama.chat(
        model=model,
        messages=messages,
        think=False,
        options={"temperature": temperature, "num_ctx": num_ctx, "stop": _STOP},
        stream=True,
    ):
        try:
            token = chunk.message.content or ""
        except AttributeError:
            token = chunk.get("message", {}).get("content", "") or ""
        if not token:
            continue
        if header_stripped:
            yield token
        else:
            buf += token
            # Buffer until we have enough to safely check for a leading fragment
            if len(buf) >= 30 or "\n" in buf:
                buf = _strip_leading_fragment(buf)
                header_stripped = True
                if buf:
                    yield buf
                buf = ""
    # Flush any remaining buffer (short response that never hit the threshold)
    if buf:
        yield _strip_leading_fragment(buf)

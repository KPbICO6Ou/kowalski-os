"""LLM client protocol + Ollama implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class ChatChunk:
    content_delta: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False


class LLMClient(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatChunk]: ...


class OllamaLLM:
    def __init__(self, host: str, model: str):
        import ollama

        self._client = ollama.AsyncClient(host=host)
        self.model = model

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatChunk]:
        stream = await self._client.chat(
            model=self.model, messages=messages, tools=tools or None, stream=True
        )
        async for part in stream:
            message = part.get("message", {}) if isinstance(part, dict) else part.message
            content = (
                message.get("content", "") if isinstance(message, dict) else message.content or ""
            )
            raw_calls = (
                message.get("tool_calls") if isinstance(message, dict) else message.tool_calls
            ) or []
            calls = []
            for raw in raw_calls:
                fn = raw["function"] if isinstance(raw, dict) else raw.function
                name = fn["name"] if isinstance(fn, dict) else fn.name
                args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
                if not isinstance(args, dict):
                    import json

                    try:
                        args = json.loads(args)
                    except (TypeError, ValueError):
                        args = {}
                calls.append(ToolCall(name=name, args=args))
            done = bool(part.get("done") if isinstance(part, dict) else part.done)
            yield ChatChunk(content_delta=content, tool_calls=calls, done=done)

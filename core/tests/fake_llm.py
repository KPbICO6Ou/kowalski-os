"""Scripted LLM client for tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from kowalski.agent.llm import ChatChunk, ToolCall


class FakeLLM:
    """Replays a script: each turn is either a text answer (str) or a list of ToolCall."""

    def __init__(self, script: list[str | list[ToolCall]]):
        self.script = list(script)
        self.calls: list[list[dict[str, Any]]] = []  # captured message lists

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append(list(messages))
        if not self.script:
            yield ChatChunk(content_delta="(script exhausted)", done=True)
            return
        turn = self.script.pop(0)
        if isinstance(turn, str):
            # stream word by word to exercise token events
            for word in turn.split(" "):
                yield ChatChunk(content_delta=word + " ")
            yield ChatChunk(done=True)
        else:
            yield ChatChunk(tool_calls=turn, done=True)

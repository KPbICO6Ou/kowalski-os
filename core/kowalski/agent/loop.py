"""The agent loop: LLM chat -> validate tool calls -> policy -> execute -> repeat.

Invalid tool calls (bad args / unknown tool) are fed back to the model as
role=tool messages with the expected schema, with a consecutive-failure cap —
the retry loop for local models whose tool calling is imperfect."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ..tools.base import InvalidToolArgsError, UnknownToolError
from ..tools.registry import ToolRegistry
from .events import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from .llm import LLMClient, ToolCall
from .prompts import build_system_prompt

MAX_CONSECUTIVE_INVALID = 3


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        max_iterations: int = 8,
        context_provider=None,
    ):
        self.llm = llm
        self.registry = registry
        self.max_iterations = max_iterations
        # Optional ContextProvider (memory/profile): given the user prompt it
        # returns extra system-prompt text (profile facts + recalled memories).
        self.context_provider = context_provider

    async def run(
        self,
        prompt: str,
        history: list[dict[str, Any]] | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        conversation_id = conversation_id or uuid.uuid4().hex
        system = build_system_prompt()
        if self.context_provider is not None:
            try:
                extra = await self.context_provider.context_for(prompt)
            except Exception:  # memory must never break a turn
                extra = ""
            if extra:
                system += "\n\n" + extra
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *(history or []),
            {"role": "user", "content": prompt},
        ]
        tools = self.registry.schemas_for_ollama()
        answer_parts: list[str] = []
        invalid_streak = 0

        for _ in range(self.max_iterations):
            content_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            try:
                async for chunk in self.llm.chat(messages, tools):
                    if chunk.content_delta:
                        content_parts.append(chunk.content_delta)
                        yield TokenEvent(text=chunk.content_delta)
                    tool_calls.extend(chunk.tool_calls)
            except Exception as exc:
                yield ErrorEvent(message=f"LLM error: {exc}")
                return

            content = "".join(content_parts)
            if not tool_calls:
                answer_parts.append(content)
                yield DoneEvent(answer="".join(answer_parts))
                return

            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {"function": {"name": c.name, "arguments": c.args}} for c in tool_calls
                    ],
                }
            )

            for call in tool_calls:
                yield ToolCallEvent(tool=call.name, args=call.args)
                try:
                    result = await self.registry.execute(
                        call.name, call.args, conversation_id=conversation_id
                    )
                except UnknownToolError:
                    invalid_streak += 1
                    if invalid_streak >= MAX_CONSECUTIVE_INVALID:
                        yield ErrorEvent(message="too many invalid tool calls, aborting")
                        return
                    available = ", ".join(t.name for t in self.registry.list())
                    messages.append(
                        {
                            "role": "tool",
                            "content": f"Error: unknown tool '{call.name}'."
                            f" Available tools: {available}",
                        }
                    )
                    continue
                except InvalidToolArgsError as exc:
                    invalid_streak += 1
                    if invalid_streak >= MAX_CONSECUTIVE_INVALID:
                        yield ErrorEvent(message="too many invalid tool calls, aborting")
                        return
                    messages.append(
                        {
                            "role": "tool",
                            "content": f"Error: invalid arguments for {call.name}: {exc}\n"
                            f"Expected schema: {json.dumps(exc.schema)}",
                        }
                    )
                    continue

                invalid_streak = 0
                yield ToolResultEvent(tool=call.name, ok=result.ok, content=result.content)
                messages.append({"role": "tool", "content": result.content})

        yield ErrorEvent(
            message=f"reached max iterations ({self.max_iterations}) without a final answer"
        )

"""LLM transport through pydantic-ai (`pydantic_ai.direct.model_request_stream`).

Conforms to the same LLMClient protocol as OllamaLLM, so the agent loop,
policy and journal are unchanged — only the wire layer differs. Select with
KOW_LLM=pydantic-ai. Any pydantic-ai model string works via KOW_PAI_MODEL
(e.g. "anthropic:claude-sonnet-4-6"); the default wraps the configured Ollama
host through its OpenAI-compatible endpoint."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from .llm import ChatChunk, ToolCall


def _build_model(host: str, model: str, pai_model: str = ""):
    if pai_model:
        return pai_model  # provider-prefixed string, resolved by pydantic-ai
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider

    return OpenAIChatModel(
        model, provider=OllamaProvider(base_url=f"{host.rstrip('/')}/v1")
    )


def to_pai_messages(messages: list[dict[str, Any]]):
    """Convert the loop's role-dict history into pydantic-ai ModelMessages.

    role=tool entries are paired in order with the tool_calls of the closest
    preceding assistant message (the loop emits them strictly in that order)."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        SystemPromptPart,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    result = []
    pending_calls: list[tuple[str, str]] = []  # (tool_name, call_id) awaiting returns
    call_counter = 0

    for message in messages:
        role = message["role"]
        if role == "system":
            result.append(ModelRequest(parts=[SystemPromptPart(content=message["content"])]))
        elif role == "user":
            result.append(ModelRequest(parts=[UserPromptPart(content=message["content"])]))
        elif role == "assistant":
            parts = []
            if message.get("content"):
                parts.append(TextPart(content=message["content"]))
            pending_calls = []
            for raw in message.get("tool_calls") or []:
                fn = raw["function"]
                call_id = f"call_{call_counter}"
                call_counter += 1
                pending_calls.append((fn["name"], call_id))
                parts.append(
                    ToolCallPart(tool_name=fn["name"], args=fn["arguments"], tool_call_id=call_id)
                )
            result.append(ModelResponse(parts=parts))
        elif role == "tool":
            tool_name, call_id = (
                pending_calls.pop(0) if pending_calls else ("unknown", f"call_{call_counter}")
            )
            result.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=tool_name,
                            content=message["content"],
                            tool_call_id=call_id,
                        )
                    ]
                )
            )
    return result


def to_tool_definitions(tools: list[dict[str, Any]]):
    """Our registry exports OpenAI/Ollama-style schemas; map them to
    pydantic-ai ToolDefinitions."""
    from pydantic_ai.tools import ToolDefinition

    return [
        ToolDefinition(
            name=tool["function"]["name"],
            description=tool["function"]["description"],
            parameters_json_schema=tool["function"]["parameters"],
        )
        for tool in tools
    ]


def _parse_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


class PydanticAILLM:
    def __init__(self, host: str, model: str, pai_model: str = "", temperature: float = 0.2):
        self.model = _build_model(host, model, pai_model)
        self.temperature = temperature

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[ChatChunk]:
        from pydantic_ai.direct import model_request_stream
        from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, TextPart, TextPartDelta
        from pydantic_ai.models import ModelRequestParameters
        from pydantic_ai.settings import ModelSettings

        params = ModelRequestParameters(
            function_tools=to_tool_definitions(tools), allow_text_output=True
        )
        async with model_request_stream(
            self.model,
            to_pai_messages(messages),
            model_request_parameters=params,
            model_settings=ModelSettings(temperature=self.temperature),
        ) as stream:
            async for event in stream:
                # stream text live; tool calls are taken complete from the final
                # response below (arg deltas may be partial JSON fragments)
                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                    if event.part.content:
                        yield ChatChunk(content_delta=event.part.content)
                elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                    if event.delta.content_delta:
                        yield ChatChunk(content_delta=event.delta.content_delta)

            response = stream.get()

        calls = [
            ToolCall(name=part.tool_name, args=_parse_args(part.args))
            for part in response.parts
            if getattr(part, "part_kind", "") == "tool-call"
        ]
        yield ChatChunk(tool_calls=calls, done=True)

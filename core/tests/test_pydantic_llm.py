"""Tests for the pydantic-ai transport layer (message/tool conversion)."""

import pytest

pytest.importorskip("pydantic_ai")

from kowalski.agent.pydantic_llm import (  # noqa: E402
    _parse_args,
    to_pai_messages,
    to_tool_definitions,
)


def test_message_conversion_roles():
    history = [
        {"role": "system", "content": "you are kowalski"},
        {"role": "user", "content": "find my files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "files.search_by_name", "arguments": {"pattern": "*.md"}}},
                {"function": {"name": "system.info", "arguments": {}}},
            ],
        },
        {"role": "tool", "content": "Found 3 files"},
        {"role": "tool", "content": '{"cpu": {}}'},
        {"role": "user", "content": "thanks"},
    ]
    converted = to_pai_messages(history)
    kinds = [type(m).__name__ for m in converted]
    assert kinds == [
        "ModelRequest", "ModelRequest", "ModelResponse",
        "ModelRequest", "ModelRequest", "ModelRequest",
    ]
    # tool returns are paired with the assistant's calls, in order
    first_return = converted[3].parts[0]
    second_return = converted[4].parts[0]
    assert first_return.tool_name == "files.search_by_name"
    assert second_return.tool_name == "system.info"
    assert first_return.tool_call_id != second_return.tool_call_id


def test_tool_definitions_mapping():
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "notes.create",
                "description": "Save a note",
                "parameters": {"type": "object", "properties": {"title": {"type": "string"}}},
            },
        }
    ]
    defs = to_tool_definitions(schemas)
    assert defs[0].name == "notes.create"
    assert defs[0].parameters_json_schema["properties"]["title"]["type"] == "string"


def test_parse_args_variants():
    assert _parse_args({"a": 1}) == {"a": 1}
    assert _parse_args('{"a": 1}') == {"a": 1}
    assert _parse_args("") == {}
    assert _parse_args("not json") == {}
    assert _parse_args(None) == {}
    assert _parse_args("[1,2]") == {}  # non-dict JSON

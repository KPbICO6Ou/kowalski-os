"""Tests for the MCP client connector (kowalski.tools.mcp).

All tests mock at the SDK boundary -- they never spawn a real MCP server,
never touch the network, and pass whether or not the optional ``mcp`` SDK is
installed (we monkeypatch the two seam functions that touch it).
"""

from __future__ import annotations

from typing import Any

from kowalski.config import Config
from kowalski.tools import mcp as mcpmod
from kowalski.tools.base import RiskLevel


# --- fakes mirroring the bits of the MCP SDK we consume -----------------------


class FakeTool:
    """Stand-in for mcp.types.Tool."""

    def __init__(self, name: str, description: str, input_schema: dict[str, Any] | None):
        self.name = name
        self.description = description
        self.inputSchema = input_schema


class FakeTextBlock:
    """Stand-in for mcp.types.TextContent."""

    def __init__(self, text: str):
        self.text = text


class FakeCallResult:
    """Stand-in for mcp.types.CallToolResult."""

    def __init__(self, text: str, is_error: bool = False):
        self.content = [FakeTextBlock(text)]
        self.isError = is_error


def _config(servers: str) -> Config:
    return Config({"KOW_MCP_SERVERS": servers})


# --- parsing ------------------------------------------------------------------


def test_empty_config_returns_empty_list():
    assert mcpmod.build_mcp_tools(_config("")) == []


def test_parse_server_specs_basic():
    specs = mcpmod.parse_server_specs("srv=python -m server;other=node app.js --flag")
    assert len(specs) == 2
    assert specs[0].name == "srv"
    assert specs[0].command == "python"
    assert specs[0].args == ["-m", "server"]
    assert specs[1].name == "other"
    assert specs[1].command == "node"
    assert specs[1].args == ["app.js", "--flag"]


def test_parse_server_specs_skips_malformed():
    specs = mcpmod.parse_server_specs("noeq;  ;empty=  ;good=cmd")
    names = [s.name for s in specs]
    assert names == ["good"]


# --- JSON-schema -> pydantic mapping ------------------------------------------


def test_schema_mapping_types_and_required():
    schema = {
        "type": "object",
        "properties": {
            "s": {"type": "string"},
            "i": {"type": "integer"},
            "n": {"type": "number"},
            "b": {"type": "boolean"},
            "arr": {"type": "array"},
            "obj": {"type": "object"},
        },
        "required": ["s", "i"],
    }
    model = mcpmod._model_from_input_schema("M", schema)
    fields = model.model_fields
    assert fields["s"].annotation is str
    assert fields["i"].annotation is int
    assert fields["n"].annotation == (float | None)
    assert fields["b"].annotation == (bool | None)
    assert fields["arr"].annotation == (list | None)
    assert fields["obj"].annotation == (dict | None)
    # required fields have no default; optional ones default to None
    assert fields["s"].is_required()
    assert fields["i"].is_required()
    assert not fields["n"].is_required()
    instance = model(s="x", i=3)
    assert instance.n is None and instance.b is None


def test_schema_mapping_empty_and_missing():
    assert mcpmod._model_from_input_schema("Empty", None).model_fields == {}
    assert mcpmod._model_from_input_schema("Empty2", {}).model_fields == {}
    assert mcpmod._model_from_input_schema("Empty3", {"type": "object"}).model_fields == {}


def test_schema_mapping_unknown_type_falls_back_to_any():
    schema = {"properties": {"x": {"type": "weird"}}, "required": ["x"]}
    model = mcpmod._model_from_input_schema("M", schema)
    # Any-typed field accepts anything
    assert model(x={"nested": 1}).x == {"nested": 1}


# --- build_mcp_tools with a fake server ---------------------------------------


def test_build_exposes_namespaced_tool(monkeypatch):
    tool = FakeTool(
        name="search",
        description="search the web",
        input_schema={"properties": {"q": {"type": "string"}}, "required": ["q"]},
    )

    def fake_list(spec):
        assert spec.name == "srv"
        return [tool]

    monkeypatch.setattr(mcpmod, "_list_remote_tools", fake_list)
    tools = mcpmod.build_mcp_tools(_config("srv=python server.py"))
    assert len(tools) == 1
    td = tools[0]
    assert td.name == "srv.search"
    assert td.description == "search the web"
    assert td.risk == RiskLevel.NETWORK
    assert "q" in td.input_schema["properties"]
    assert td.input_schema["required"] == ["q"]


async def test_handler_routes_to_session_call_tool(monkeypatch):
    tool = FakeTool(
        name="search",
        description="search",
        input_schema={"properties": {"q": {"type": "string"}}, "required": ["q"]},
    )
    monkeypatch.setattr(mcpmod, "_list_remote_tools", lambda spec: [tool])

    captured: dict[str, Any] = {}

    async def fake_call(spec, tool_name, arguments):
        captured["spec"] = spec.name
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return FakeCallResult("hello from fake")

    monkeypatch.setattr(mcpmod, "_call_remote_tool", fake_call)

    td = mcpmod.build_mcp_tools(_config("srv=python server.py"))[0]
    args = td.args_model(q="cats")
    result = await td.handler(args)

    assert result.ok
    assert result.content == "hello from fake"
    assert captured == {"spec": "srv", "tool_name": "search", "arguments": {"q": "cats"}}
    assert isinstance(result.data, FakeCallResult)


async def test_handler_error_result_marks_not_ok(monkeypatch):
    tool = FakeTool("boom", "fails", {"properties": {}})
    monkeypatch.setattr(mcpmod, "_list_remote_tools", lambda spec: [tool])

    async def fake_call(spec, tool_name, arguments):
        return FakeCallResult("kaboom", is_error=True)

    monkeypatch.setattr(mcpmod, "_call_remote_tool", fake_call)
    td = mcpmod.build_mcp_tools(_config("srv=python s.py"))[0]
    result = await td.handler(td.args_model())
    assert not result.ok
    assert result.content == "kaboom"


async def test_handler_exception_wrapped(monkeypatch):
    tool = FakeTool("t", "t", {"properties": {}})
    monkeypatch.setattr(mcpmod, "_list_remote_tools", lambda spec: [tool])

    async def fake_call(spec, tool_name, arguments):
        raise RuntimeError("server died")

    monkeypatch.setattr(mcpmod, "_call_remote_tool", fake_call)
    td = mcpmod.build_mcp_tools(_config("srv=python s.py"))[0]
    result = await td.handler(td.args_model())
    assert not result.ok
    assert "server died" in result.content


async def test_handler_missing_sdk_hint(monkeypatch):
    tool = FakeTool("t", "t", {"properties": {}})
    monkeypatch.setattr(mcpmod, "_list_remote_tools", lambda spec: [tool])

    async def fake_call(spec, tool_name, arguments):
        raise ImportError("no module named mcp")

    monkeypatch.setattr(mcpmod, "_call_remote_tool", fake_call)
    td = mcpmod.build_mcp_tools(_config("srv=python s.py"))[0]
    result = await td.handler(td.args_model())
    assert not result.ok
    assert "pip install mcp" in result.content


# --- resilience: one bad server must not break the others ---------------------


def test_failing_server_is_skipped(monkeypatch):
    good = FakeTool("ping", "ping", {"properties": {}})

    def fake_list(spec):
        if spec.name == "bad":
            raise RuntimeError("could not launch")
        return [good]

    monkeypatch.setattr(mcpmod, "_list_remote_tools", fake_list)
    tools = mcpmod.build_mcp_tools(_config("bad=nope;good=python s.py"))
    names = {t.name for t in tools}
    assert names == {"good.ping"}


def test_missing_sdk_skips_server(monkeypatch):
    def fake_list(spec):
        raise ImportError("no mcp")

    monkeypatch.setattr(mcpmod, "_list_remote_tools", fake_list)
    # no exception, just an empty result + a logged hint
    assert mcpmod.build_mcp_tools(_config("srv=python s.py")) == []


# --- registry integration: remote tool flows through the choke point ----------


async def test_remote_tool_through_registry(monkeypatch, registry):
    tool = FakeTool(
        name="echo",
        description="echo",
        input_schema={"properties": {"msg": {"type": "string"}}, "required": ["msg"]},
    )
    monkeypatch.setattr(mcpmod, "_list_remote_tools", lambda spec: [tool])

    async def fake_call(spec, tool_name, arguments):
        return FakeCallResult(f"echo: {arguments['msg']}")

    monkeypatch.setattr(mcpmod, "_call_remote_tool", fake_call)
    registry.register_all(mcpmod.build_mcp_tools(_config("srv=python s.py")))
    result = await registry.execute("srv.echo", {"msg": "hi"})
    assert result.ok
    assert result.content == "echo: hi"

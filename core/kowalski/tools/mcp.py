"""MCP client connector: mount tools from external Model Context Protocol
servers into the kowalski ToolRegistry.

Each remote tool becomes a namespaced ToolDef (``server.tool``) so calls still
flow through the kowalski choke point: pydantic validation -> security policy
-> confirmation -> journal. Remote tools default to RiskLevel.NETWORK (external
process, unknown side effects) so the policy confirms them.

Lifecycle (tradeoff): we open a *fresh* stdio session per operation -- once to
list tools at build time, then once per handler call. This is the simplest
correct approach for a scaffold: no long-lived subprocess to supervise, no
shared session state to guard across concurrent tool calls, and a crashed
server only fails the call in flight. The cost is subprocess spawn latency on
every call; a persistent pooled session would be faster but needs lifecycle
management (restart on crash, concurrency control) out of scope here.

The ``mcp`` SDK is an optional dependency and is imported lazily, so importing
this module never requires it. A server that fails to start, initialize, or
list tools is logged and skipped -- it never breaks the rest of the registry.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import create_model

from ..config import Config
from .base import RiskLevel, ToolDef, ToolResult

log = logging.getLogger(__name__)

# JSON Schema primitive type -> python type for pydantic field annotations.
_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


class _ServerSpec:
    """A parsed MCP server entry: a name plus the command/args to launch it."""

    __slots__ = ("name", "command", "args")

    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.command = command
        self.args = args


def parse_server_specs(raw: str) -> list[_ServerSpec]:
    """Parse ``KOW_MCP_SERVERS``.

    Format: ``name=command arg arg;name2=command2 ...`` -- semicolon-separated
    servers; ``name`` is the namespace, the first whitespace token after ``=``
    is the executable and the rest are its args. Malformed entries are skipped.
    """
    specs: list[_ServerSpec] = []
    for chunk in raw.split(";"):
        entry = chunk.strip()
        if not entry:
            continue
        name, sep, command_line = entry.partition("=")
        name = name.strip()
        if not sep or not name:
            log.warning("MCP: ignoring malformed server spec %r (expected name=command)", entry)
            continue
        tokens = command_line.split()
        if not tokens:
            log.warning("MCP: ignoring server %r with empty command", name)
            continue
        specs.append(_ServerSpec(name=name, command=tokens[0], args=tokens[1:]))
    return specs


def _model_from_input_schema(model_name: str, schema: dict[str, Any] | None) -> type:
    """Build a pydantic model from a JSON Schema's top-level ``properties``.

    Missing/empty schema -> a model with no fields. Unknown property types fall
    back to ``Any``. Fields not in ``required`` are Optional with a None default.
    """
    if not schema or not isinstance(schema, dict):
        return create_model(model_name)
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return create_model(model_name)
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        json_type = None
        if isinstance(prop_schema, dict):
            json_type = prop_schema.get("type")
        py_type: Any = _JSON_TYPE_MAP.get(json_type, Any) if json_type else Any
        if prop_name in required:
            fields[prop_name] = (py_type, ...)
        else:
            fields[prop_name] = (py_type | None, None)
    return create_model(model_name, **fields)


def _content_to_text(result: Any) -> str:
    """Flatten an MCP CallToolResult's content blocks into a single text string."""
    content = getattr(result, "content", None)
    if content is None:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(block))
    return "\n".join(parts)


async def _call_remote_tool(spec: _ServerSpec, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Open a fresh stdio session, call ``tool_name``, return the raw result.

    Raises ImportError if the ``mcp`` SDK is absent. The session boundary lives
    here so tests can monkeypatch this single function with a fake.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=spec.command, args=spec.args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


def _make_handler(spec: _ServerSpec, tool_name: str):
    """Build an async handler that opens a fresh stdio session and calls the tool."""

    async def handler(args) -> ToolResult:
        try:
            result = await _call_remote_tool(spec, tool_name, args.model_dump())
        except ImportError:
            return ToolResult(
                ok=False,
                content="MCP SDK not installed; run: pip install mcp",
                data=None,
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure as a tool error
            return ToolResult(ok=False, content=f"MCP call failed: {exc}", data=None)
        ok = not bool(getattr(result, "isError", False))
        return ToolResult(ok=ok, content=_content_to_text(result), data=result)

    return handler


def build_mcp_tools(config: Config) -> list[ToolDef]:
    """Connect to each configured MCP server and expose its tools as ToolDefs.

    Reads the ``KOW_MCP_SERVERS`` config key (see :func:`parse_server_specs`).
    Empty config -> ``[]``. Servers that cannot be reached, or the missing
    ``mcp`` SDK, are logged and skipped -- never raised.
    """
    raw = config.get("KOW_MCP_SERVERS", "")
    specs = parse_server_specs(raw)
    if not specs:
        return []

    tools: list[ToolDef] = []
    for spec in specs:
        try:
            remote_tools = _list_remote_tools(spec)
        except ImportError:
            log.warning(
                "MCP: 'mcp' SDK not installed; skipping server %r. Run: pip install mcp",
                spec.name,
            )
            continue
        except Exception as exc:  # noqa: BLE001 - one bad server must not break the rest
            log.warning("MCP: failed to load server %r (%s); skipping", spec.name, exc)
            continue
        for remote in remote_tools:
            tool_name = remote.name
            description = (getattr(remote, "description", None) or tool_name).strip()
            schema = getattr(remote, "inputSchema", None)
            args_model = _model_from_input_schema(f"{spec.name}_{tool_name}_Args", schema)
            tools.append(
                ToolDef(
                    name=f"{spec.name}.{tool_name}",
                    description=description,
                    args_model=args_model,
                    risk=RiskLevel.NETWORK,
                    handler=_make_handler(spec, tool_name),
                )
            )
    return tools


def _list_remote_tools(spec: _ServerSpec) -> list[Any]:
    """Open a short-lived stdio session to enumerate a server's tools.

    Raises ImportError if the ``mcp`` SDK is absent (caller turns it into a
    skip-with-hint); any other failure propagates for the caller to log+skip.
    """
    import asyncio

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=spec.command, args=spec.args)

    async def _run() -> list[Any]:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                return list(listed.tools)

    return asyncio.run(_run())

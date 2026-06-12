"""Mount pydantic-ai-toolbox toolsets (wachawo/pydantic-ai-toolbox) into the
kowalski ToolRegistry.

Toolbox toolsets are class-based pydantic-ai FunctionToolsets whose tool
methods carry marker attributes (see pydantic_ai_toolbox.base). We register
the *bound methods* directly, so every call still flows through the kowalski
choke point: pydantic validation -> security policy -> confirmation -> journal.
The toolsets keep their own sandboxing (e.g. FilesystemToolset root)."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from pydantic import create_model

from .base import RiskLevel, ToolDef, ToolResult

TOOL_MARKER_ATTR = "__toolset_tool__"
TOOL_NAME_ATTR = "__toolset_tool_name__"
TOOL_DESC_ATTR = "__toolset_tool_description__"

# Method-name prefixes -> risk. Anything unmatched is WRITE (safe default).
READ_PREFIXES = ("list", "read", "stat", "glob", "grep", "search", "get", "recall", "info", "query")
DESTRUCTIVE_PREFIXES = ("delete", "remove", "drop", "truncate")


def classify_risk(method_name: str) -> RiskLevel:
    if method_name.startswith(DESTRUCTIVE_PREFIXES):
        return RiskLevel.DESTRUCTIVE
    if method_name.startswith(READ_PREFIXES):
        return RiskLevel.READ
    return RiskLevel.WRITE


def _args_model_from_signature(name: str, fn) -> type:
    fields: dict[str, Any] = {}
    for param_name, param in inspect.signature(fn).parameters.items():
        if param_name in ("self", "ctx"):
            continue
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[param_name] = (annotation, default)
    return create_model(f"{name}_Args", **fields)


def build_tools(toolset: Any, namespace: str) -> list[ToolDef]:
    """Wrap every @tool-marked method of a toolbox toolset as a ToolDef."""
    tools: list[ToolDef] = []
    cls = type(toolset)
    for attr_name in dir(cls):
        if attr_name.startswith("_"):
            continue
        raw = getattr(cls, attr_name, None)
        if not callable(raw) or not getattr(raw, TOOL_MARKER_ATTR, False):
            continue
        bound = getattr(toolset, attr_name)
        tool_name = getattr(raw, TOOL_NAME_ATTR, None) or attr_name
        description = (
            getattr(raw, TOOL_DESC_ATTR, None) or (raw.__doc__ or "").strip() or tool_name
        )
        args_model = _args_model_from_signature(f"{namespace}_{tool_name}", raw)
        tools.append(
            ToolDef(
                name=f"{namespace}.{tool_name}",
                description=description,
                args_model=args_model,
                risk=classify_risk(tool_name),
                handler=_make_handler(bound),
            )
        )
    return tools


def _make_handler(bound_method):
    async def handler(args) -> ToolResult:
        kwargs = args.model_dump()
        if inspect.iscoroutinefunction(bound_method):
            result = await bound_method(**kwargs)
        else:
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: bound_method(**kwargs)
            )
        if isinstance(result, str):
            content = result
        else:
            content = json.dumps(result, ensure_ascii=False, default=str)
        return ToolResult(ok=True, content=content, data=result)

    return handler


def build_filesystem_tools(root, read_only: bool = True) -> list[ToolDef]:
    """fs.* tools backed by pydantic-ai-toolbox FilesystemToolset (sandboxed at root)."""
    from pydantic_ai_toolbox import FilesystemToolset

    toolset = FilesystemToolset(root=root, read_only=read_only)
    return build_tools(toolset, "fs")

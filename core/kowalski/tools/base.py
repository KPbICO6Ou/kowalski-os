"""Tool contracts. ToolDef mirrors the MCP Tool descriptor field-for-field
(name / description / inputSchema), so moving a tool module behind a real
MCP server later is mechanical."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    NETWORK = "network"


@dataclass
class ToolResult:
    ok: bool
    content: str  # text fed back to the LLM
    data: Any = None  # structured payload for journal/API


@dataclass
class ToolDef:
    name: str  # "files.search_by_name"
    description: str
    args_model: type[BaseModel]
    risk: RiskLevel
    handler: Callable[..., Awaitable[ToolResult]]  # handler(args: BaseModel) -> ToolResult
    path_fields: tuple[str, ...] = field(default=())  # arg names holding filesystem paths
    # Optional content-aware danger check. Given the parsed args dict, returns a
    # human-readable danger reason or None. When it fires, the registry forces a
    # confirmation (even under --yes) — it flags, it never hard-blocks.
    danger_check: Callable[[dict[str, Any]], str | None] | None = None

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


class UnknownToolError(Exception):
    def __init__(self, name: str):
        super().__init__(f"unknown tool: {name}")
        self.name = name


class InvalidToolArgsError(Exception):
    def __init__(self, name: str, message: str, schema: dict[str, Any]):
        super().__init__(message)
        self.name = name
        self.schema = schema

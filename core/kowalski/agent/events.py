"""Agent events streamed to UIs (CLI, socket, D-Bus). Must stay JSON-serializable."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class AgentEvent:
    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event"] = self.__class__.__name__
        return payload


@dataclass
class TokenEvent(AgentEvent):
    text: str


@dataclass
class ToolCallEvent(AgentEvent):
    tool: str
    args: dict[str, Any]


@dataclass
class ConfirmRequestEvent(AgentEvent):
    request_id: str
    tool: str
    args: dict[str, Any]
    risk: str
    reason: str


@dataclass
class ToolResultEvent(AgentEvent):
    tool: str
    ok: bool
    content: str


@dataclass
class DoneEvent(AgentEvent):
    answer: str


@dataclass
class ErrorEvent(AgentEvent):
    message: str


@dataclass
class PlanEvent(AgentEvent):
    goal: str
    steps: list[str]


@dataclass
class PlanStepEvent(AgentEvent):
    index: int
    total: int
    description: str
    status: str  # "start" | "done"

"""Tool registry — the single choke point: validate args, evaluate policy,
ask for confirmation, execute with timeout, and journal EVERY invocation
(including denied and invalid ones)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import ValidationError

from ..journal import ActionJournal
from ..policy import ConfirmationProvider, ConfirmRequest, Decision, SecurityPolicy
from .base import InvalidToolArgsError, ToolDef, ToolResult, UnknownToolError


class ToolRegistry:
    def __init__(
        self,
        policy: SecurityPolicy,
        journal: ActionJournal,
        confirmer: ConfirmationProvider,
        tool_timeout: float = 30.0,
    ):
        self._tools: dict[str, ToolDef] = {}
        self.policy = policy
        self.journal = journal
        self.confirmer = confirmer
        self.tool_timeout = tool_timeout

    def register(self, tool: ToolDef) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def register_all(self, tools: list[ToolDef]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> ToolDef:
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name]

    def list(self) -> list[ToolDef]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def schemas_for_ollama(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self.list()
        ]

    async def execute(
        self, name: str, args: dict[str, Any], conversation_id: str | None = None
    ) -> ToolResult:
        """Raises UnknownToolError / InvalidToolArgsError (the agent loop turns
        those into retry messages); policy denial returns ToolResult(ok=False)."""
        try:
            tool = self.get(name)
        except UnknownToolError:
            self.journal.record(
                tool=name, args=args, risk="?", decision="unknown_tool",
                conversation_id=conversation_id, error="unknown tool",
            )
            raise

        try:
            parsed = tool.args_model(**args)
        except ValidationError as exc:
            self.journal.record(
                tool=name, args=args, risk=tool.risk, decision="invalid_args",
                conversation_id=conversation_id, error=str(exc),
            )
            raise InvalidToolArgsError(name, str(exc), tool.input_schema) from exc

        clean_args = parsed.model_dump()
        decision, reason = self.policy.evaluate(tool, clean_args)

        if decision == Decision.DENY:
            self.journal.record(
                tool=name, args=clean_args, risk=tool.risk, decision="denied_by_policy",
                conversation_id=conversation_id, error=reason,
            )
            return ToolResult(ok=False, content=f"Denied by security policy: {reason}")

        if decision == Decision.CONFIRM:
            approved = await self.confirmer.confirm(
                ConfirmRequest(tool=name, args=clean_args, risk=tool.risk, reason=reason)
            )
            if not approved:
                self.journal.record(
                    tool=name, args=clean_args, risk=tool.risk, decision="denied_by_user",
                    conversation_id=conversation_id,
                )
                return ToolResult(ok=False, content="Denied by user.")

        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(tool.handler(parsed), timeout=self.tool_timeout)
        except TimeoutError:
            duration = int((time.perf_counter() - started) * 1000)
            self.journal.record(
                tool=name, args=clean_args, risk=tool.risk, decision="executed",
                conversation_id=conversation_id, result_ok=False,
                duration_ms=duration, error="timeout",
            )
            return ToolResult(ok=False, content=f"Tool timed out after {self.tool_timeout}s.")
        except Exception as exc:  # tool bugs must not kill the agent loop
            duration = int((time.perf_counter() - started) * 1000)
            self.journal.record(
                tool=name, args=clean_args, risk=tool.risk, decision="executed",
                conversation_id=conversation_id, result_ok=False,
                duration_ms=duration, error=repr(exc),
            )
            return ToolResult(ok=False, content=f"Tool failed: {exc}")

        duration = int((time.perf_counter() - started) * 1000)
        self.journal.record(
            tool=name, args=clean_args, risk=tool.risk, decision="executed",
            conversation_id=conversation_id, result_ok=result.ok,
            result_excerpt=result.content, duration_ms=duration,
        )
        return result

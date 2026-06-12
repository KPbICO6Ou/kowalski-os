"""Omnibox controller: pure asyncio glue between OmniClient and a view.

No UI imports here — views (tty, GTK) plug in via the Callbacks protocol so the
streaming logic stays testable without any toolkit installed.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from .client import OmniClient


class Callbacks(Protocol):
    """View-side hooks invoked by the controller while an ask streams."""

    def on_token(self, text: str) -> None: ...

    def on_tool(self, tool: str, args: dict[str, Any]) -> None: ...

    def on_tool_result(self, tool: str, ok: bool, content: str) -> None: ...

    def on_confirm_request(
        self, request_id: str, tool: str, args: dict[str, Any], risk: str, reason: str
    ) -> None: ...

    def on_done(self, answer: str) -> None: ...

    def on_error(self, message: str) -> None: ...


class OmniController:
    """Drives asks against the daemon and fans events out to view callbacks.

    One controller instance keeps a single conversation_id, so every prompt
    submitted during an omnibox session lands in the same conversation.
    """

    def __init__(self, client: OmniClient, callbacks: Callbacks):
        self.client = client
        self.callbacks = callbacks
        self.conversation_id = uuid.uuid4().hex

    async def submit(self, prompt: str) -> None:
        """Run one ask to completion, dispatching each event to the callbacks."""
        try:
            async for event in self.client.ask(prompt, self.conversation_id):
                self._dispatch(event)
        except Exception as exc:  # surface transport failures the same way as ErrorEvent
            self.callbacks.on_error(str(exc))

    async def answer_confirm(self, request_id: str, approved: bool) -> bool:
        """Answer a pending confirmation on a separate connection."""
        return await self.client.confirm(request_id, approved)

    def _dispatch(self, event: dict) -> None:
        cb = self.callbacks
        kind = event.get("event")
        if kind == "TokenEvent":
            cb.on_token(event.get("text", ""))
        elif kind == "ToolCallEvent":
            cb.on_tool(event.get("tool", ""), event.get("args", {}))
        elif kind == "ToolResultEvent":
            cb.on_tool_result(
                event.get("tool", ""), bool(event.get("ok")), event.get("content", "")
            )
        elif kind == "ConfirmRequestEvent":
            cb.on_confirm_request(
                event.get("request_id", ""),
                event.get("tool", ""),
                event.get("args", {}),
                event.get("risk", ""),
                event.get("reason", ""),
            )
        elif kind == "DoneEvent":
            cb.on_done(event.get("answer", ""))
        elif kind == "ErrorEvent":
            cb.on_error(event.get("message", ""))
        # unknown event kinds are ignored: forward-compatible with newer daemons

"""AgentSession over the kow-core unix socket (the same newline-delimited JSON
protocol the omnibox uses). Streams TokenEvent text; tool-call confirmations are
auto-denied, since a voice turn has no GUI to approve a risky action — so
destructive tools are blocked over voice by design.

Built on the canonical ``kowalski.ipc.client.AgentClient``; ``DaemonUnavailableError``
is re-exported here for backward-compatible imports.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from kowalski.ipc.client import AgentClient, DaemonUnavailableError

__all__ = ["DaemonUnavailableError", "SocketAgentSession"]


class SocketAgentSession:
    def __init__(self, socket_path: Path, conversation_id: str | None = None) -> None:
        self.socket_path = Path(socket_path)
        self.conversation_id = conversation_id
        self._client = AgentClient(self.socket_path)

    async def ask(self, text: str) -> AsyncIterator[str]:
        async for event in self._client.ask(text, self.conversation_id):
            kind = event.get("event")
            if kind == "TokenEvent":
                yield event.get("text", "")
            elif kind == "ConfirmRequestEvent":
                await self._client.confirm(event["request_id"], False)
            elif kind in ("DoneEvent", "ErrorEvent"):
                break

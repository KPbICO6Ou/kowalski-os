"""AgentSession over the kow-core unix socket (the same newline-delimited JSON
protocol the omnibox uses). Streams TokenEvent text; tool-call confirmations are
auto-denied, since a voice turn has no GUI to approve a risky action — so
destructive tools are blocked over voice by design.

NOTE: this speaks the same protocol as ui/kowui/client.py. A shared
`kowalski.ipc.client` in core would remove the duplication — tracked for later."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path


class DaemonUnavailableError(RuntimeError):
    pass


class SocketAgentSession:
    def __init__(self, socket_path: Path, conversation_id: str | None = None) -> None:
        self.socket_path = Path(socket_path)
        self.conversation_id = conversation_id

    async def ask(self, text: str) -> AsyncIterator[str]:
        try:
            reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise DaemonUnavailableError(
                f"kow-core not reachable at {self.socket_path} — start it with `kow serve`"
            ) from exc

        request = {"op": "ask", "prompt": text}
        if self.conversation_id:
            request["conversation_id"] = self.conversation_id
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                event = json.loads(line)
                kind = event.get("event")
                if kind == "TokenEvent":
                    yield event.get("text", "")
                elif kind == "ConfirmRequestEvent":
                    await self._deny(event["request_id"])
                elif kind in ("DoneEvent", "ErrorEvent"):
                    break
        finally:
            writer.close()

    async def _deny(self, request_id: str) -> None:
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
        writer.write(
            (json.dumps({"op": "confirm", "request_id": request_id, "approved": False}) + "\n").encode()
        )
        await writer.drain()
        await reader.readline()
        writer.close()

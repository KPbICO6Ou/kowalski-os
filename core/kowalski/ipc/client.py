"""Canonical async client for the kow-core unix-socket IPC.

Protocol: newline-delimited JSON frames (see ``socket_service.py``).
An "ask" streams ``AgentEvent`` dicts over one connection until DoneEvent/
ErrorEvent (inclusive); "confirm"/"status"/"tools"/"conversations" each use a
separate short-lived connection that yields a single reply line.

Dependency-free: stdlib asyncio + json only. This is the single source of truth
the omnibox (``kowui``) and voice (``kowvoice``) adapters build upon.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

_TERMINAL_EVENTS = ("DoneEvent", "ErrorEvent")


class DaemonUnavailableError(RuntimeError):
    """The kow-core daemon socket is not reachable.

    The message always names the socket path and points at ``kow serve`` so a
    caller can surface an actionable error verbatim.
    """

    def __init__(self, socket_path: Path | str, cause: Exception | None = None):
        self.socket_path = Path(socket_path)
        detail = f" ({cause})" if cause else ""
        super().__init__(
            f"kow-core daemon is not reachable at {self.socket_path}{detail} — "
            "start it with `kow serve` (or check KOW_SOCKET_PATH)."
        )


class AgentClient:
    """Async client over the kow-core socket IPC.

    Usage::

        client = AgentClient()
        async for event in client.ask("hello", conversation_id):
            ...
    """

    def __init__(self, socket_path: Path | str | None = None):
        if socket_path is None:
            from ..config import Config

            socket_path = Config.load().socket_path
        self.socket_path = Path(socket_path)

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            return await asyncio.open_unix_connection(str(self.socket_path))
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            raise DaemonUnavailableError(self.socket_path, exc) from exc

    @staticmethod
    async def _close(writer: asyncio.StreamWriter) -> None:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError):
            pass

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, payload: dict) -> None:
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await writer.drain()

    async def ask(
        self, prompt: str, conversation_id: str | None = None
    ) -> AsyncIterator[dict]:
        """Stream events for one prompt; one connection per ask.

        Yields parsed event dicts and returns after DoneEvent/ErrorEvent
        (inclusive), or when the daemon closes the connection.
        """
        reader, writer = await self._connect()
        try:
            request: dict = {"op": "ask", "prompt": prompt}
            if conversation_id is not None:
                request["conversation_id"] = conversation_id
            await self._send(writer, request)
            while True:
                line = await reader.readline()
                if not line:
                    break
                event = json.loads(line)
                yield event
                if event.get("event") in _TERMINAL_EVENTS:
                    break
        finally:
            await self._close(writer)

    async def _request(self, payload: dict) -> dict:
        """Send one request on a short-lived connection and return the reply."""
        reader, writer = await self._connect()
        try:
            await self._send(writer, payload)
            line = await reader.readline()
            if not line:
                raise DaemonUnavailableError(self.socket_path)
            return json.loads(line)
        finally:
            await self._close(writer)

    async def confirm(self, request_id: str, approved: bool) -> bool:
        """Answer a pending confirmation on a separate connection from the ask."""
        response = await self._request(
            {"op": "confirm", "request_id": request_id, "approved": approved}
        )
        return bool(response.get("ok"))

    async def status(self) -> dict:
        return await self._request({"op": "status"})

    async def tools(self) -> list[dict]:
        response = await self._request({"op": "tools"})
        return response.get("tools", [])

    async def conversations(self) -> list[dict]:
        response = await self._request({"op": "conversations"})
        return response.get("conversations", [])

"""Async client for the kow-core unix-socket IPC.

Protocol: newline-delimited JSON frames (see core/kowalski/ipc/socket_service.py).
An "ask" streams AgentEvent dicts over one connection until DoneEvent/ErrorEvent;
"confirm" answers a pending ConfirmRequestEvent over a separate short connection.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from kowalski.config import Config

_TERMINAL_EVENTS = ("DoneEvent", "ErrorEvent")


class DaemonUnavailableError(ConnectionError):
    """The kow-core daemon socket is not reachable."""

    def __init__(self, socket_path: Path, cause: Exception | None = None):
        self.socket_path = socket_path
        detail = f" ({cause})" if cause else ""
        super().__init__(
            f"kow-core daemon is not reachable at {socket_path}{detail}. "
            "Start it with `kow serve` (or check KOW_SOCKET_PATH)."
        )


def default_socket_path() -> Path:
    """Resolve the daemon socket path the same way kow-core does."""
    return Config.load().socket_path


class OmniClient:
    """Thin async client over the kow-core socket IPC.

    Usage::

        async with OmniClient() as client:
            async for event in client.ask("hello", conversation_id):
                ...
    """

    def __init__(self, socket_path: Path | str | None = None):
        self.socket_path = Path(socket_path) if socket_path else default_socket_path()

    async def __aenter__(self) -> "OmniClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

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

    async def ask(self, prompt: str, conversation_id: str | None = None) -> AsyncIterator[dict]:
        """Stream events for one prompt; one connection per ask.

        Yields parsed event dicts and returns after DoneEvent/ErrorEvent
        (or when the daemon closes the connection).
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
        """Send one request on a short-lived connection and return the single reply."""
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
        """Answer a pending confirmation; uses a separate connection from the ask stream."""
        response = await self._request(
            {"op": "confirm", "request_id": request_id, "approved": approved}
        )
        return bool(response.get("ok"))

    async def status(self) -> dict:
        return await self._request({"op": "status"})

    async def tools(self) -> dict:
        return await self._request({"op": "tools"})

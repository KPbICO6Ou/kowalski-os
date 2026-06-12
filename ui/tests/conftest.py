"""Fixtures: a fake kow-core daemon speaking the socket protocol with scripted events."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def short_sock_path():
    # AF_UNIX paths are limited to ~104 bytes on macOS; pytest tmp_path is too long
    sock_dir = tempfile.mkdtemp(prefix="kow", dir="/tmp")
    yield Path(sock_dir) / "kow.sock"
    shutil.rmtree(sock_dir, ignore_errors=True)


class FakeDaemon:
    """Minimal stand-in for kow-core's SocketIpcServer.

    On "ask" it replays `script` (a list of event dicts). When it emits a
    ConfirmRequestEvent it blocks until a matching "confirm" op arrives on
    another connection, recording the answer in `confirms`.
    """

    def __init__(self, socket_path: Path, script: list[dict]):
        self.socket_path = socket_path
        self.script = script
        self.asks: list[dict] = []  # raw ask requests received
        self.confirms: list[tuple[str, bool]] = []  # (request_id, approved)
        self._confirm_arrived = asyncio.Event()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_unix_server(self._handle, path=str(self.socket_path))

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                request = json.loads(line)
                op = request.get("op")
                if op == "ask":
                    self.asks.append(request)
                    for event in self.script:
                        await self._send(writer, event)
                        if event.get("event") == "ConfirmRequestEvent":
                            await asyncio.wait_for(self._confirm_arrived.wait(), timeout=5)
                elif op == "confirm":
                    self.confirms.append(
                        (request.get("request_id"), bool(request.get("approved")))
                    )
                    self._confirm_arrived.set()
                    await self._send(writer, {"ok": True})
                elif op == "status":
                    await self._send(writer, {"version": "0.1.0-fake", "tools": 2})
                elif op == "tools":
                    await self._send(writer, {"tools": [{"name": "fs.read"}, {"name": "fs.write"}]})
                else:
                    await self._send(writer, {"error": f"unknown op: {op}"})
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, payload: dict) -> None:
        writer.write((json.dumps(payload) + "\n").encode())
        await writer.drain()


SIMPLE_SCRIPT = [
    {"event": "TokenEvent", "text": "Hello"},
    {"event": "TokenEvent", "text": ", world"},
    {"event": "DoneEvent", "answer": "Hello, world"},
]

CONFIRM_SCRIPT = [
    {"event": "TokenEvent", "text": "Working"},
    {"event": "ToolCallEvent", "tool": "fs.write", "args": {"path": "/tmp/x"}},
    {
        "event": "ConfirmRequestEvent",
        "request_id": "req-1",
        "tool": "fs.write",
        "args": {"path": "/tmp/x"},
        "risk": "write",
        "reason": "writes outside the allowlist",
    },
    {"event": "ToolResultEvent", "tool": "fs.write", "ok": True, "content": "written"},
    {"event": "DoneEvent", "answer": "File written."},
]


@pytest.fixture
async def fake_daemon(short_sock_path, request):
    script = getattr(request, "param", SIMPLE_SCRIPT)
    daemon = FakeDaemon(short_sock_path, script)
    await daemon.start()
    yield daemon
    await daemon.stop()

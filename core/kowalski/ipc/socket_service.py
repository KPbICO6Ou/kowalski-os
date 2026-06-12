"""Unix-socket IPC: newline-delimited JSON frames.

Requests:
  {"op": "ask", "prompt": "...", "conversation_id": "..."}   -> stream of events, ends with done/error
  {"op": "confirm", "request_id": "...", "approved": true}   -> {"ok": true}
  {"op": "tools"}                                            -> {"tools": [...]}
  {"op": "status"}                                           -> {"version": ..., "tools": N}
  {"op": "conversations"}                                    -> {"conversations": [...]}

Events are AgentEvent.to_dict() JSON lines. ConfirmRequestEvents raised while a
tool awaits confirmation are interleaved into the same stream."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from .base import AgentService, IpcServer

log = logging.getLogger(__name__)


class SocketIpcServer(IpcServer):
    def __init__(self, socket_path: Path, service: AgentService):
        self.socket_path = socket_path
        self.service = service
        self._server: asyncio.Server | None = None

    async def serve(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self.socket_path)
        )
        os.chmod(self.socket_path, 0o600)
        log.info("socket IPC listening on %s", self.socket_path)
        async with self._server:
            await self._server.serve_forever()

    async def shutdown(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self.socket_path.exists():
            self.socket_path.unlink()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    await self._send(writer, {"error": "invalid JSON"})
                    continue
                await self._dispatch(request, writer)
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    async def _dispatch(self, request: dict, writer: asyncio.StreamWriter) -> None:
        op = request.get("op")
        if op == "ask":
            await self._handle_ask(request, writer)
        elif op == "confirm":
            ok = self.service.confirm(
                str(request.get("request_id")), bool(request.get("approved"))
            )
            await self._send(writer, {"ok": ok})
        elif op == "tools":
            await self._send(writer, {"tools": self.service.list_tools()})
        elif op == "status":
            await self._send(writer, self.service.status())
        elif op == "conversations":
            await self._send(writer, {"conversations": self.service.list_conversations()})
        else:
            await self._send(writer, {"error": f"unknown op: {op}"})

    async def _handle_ask(self, request: dict, writer: asyncio.StreamWriter) -> None:
        # Confirmation requests must reach the client through the same stream
        # while the agent loop is blocked awaiting them -> pump via queue.
        queue: asyncio.Queue = asyncio.Queue()
        self.service.confirmations.attach_queue(queue)

        async def pump_confirms():
            while True:
                event = await queue.get()
                await self._send(writer, event.to_dict())

        pump = asyncio.create_task(pump_confirms())
        try:
            async for event in self.service.ask(
                str(request.get("prompt", "")), request.get("conversation_id")
            ):
                await self._send(writer, event.to_dict())
        except Exception as exc:
            log.exception("ask failed")
            await self._send(writer, {"event": "ErrorEvent", "message": repr(exc)})
        finally:
            pump.cancel()
            self.service.confirmations.detach_queue(queue)

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, payload: dict) -> None:
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await writer.drain()

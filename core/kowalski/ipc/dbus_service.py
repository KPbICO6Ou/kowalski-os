"""D-Bus IPC: org.kowalski.Core on the session bus (Linux only, dasbus).

Methods:
  Ask(prompt: s) -> request_id: s     — events arrive as AgentEvent signals
  Confirm(request_id: s, approved: b) -> b
  ListTools() -> s (JSON)
  Status() -> s (JSON)
Signal:
  AgentEvent(request_id: s, payload_json: s)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from dasbus.connection import SessionMessageBus
from dasbus.loop import EventLoop
from dasbus.server.interface import dbus_interface, dbus_signal
from dasbus.typing import Bool, Str

from .base import AgentService, IpcServer

log = logging.getLogger(__name__)

SERVICE_NAME = "org.kowalski.Core"
OBJECT_PATH = "/org/kowalski/Core"


@dbus_interface(SERVICE_NAME)
class CoreInterface:
    def __init__(self, service: AgentService, loop: asyncio.AbstractEventLoop):
        self._service = service
        self._loop = loop

    def Ask(self, prompt: Str) -> Str:
        request_id = uuid.uuid4().hex

        async def run():
            queue: asyncio.Queue = asyncio.Queue()
            self._service.confirmations.attach_queue(queue)

            async def pump():
                while True:
                    event = await queue.get()
                    self.AgentEvent(request_id, json.dumps(event.to_dict(), ensure_ascii=False))

            pump_task = asyncio.create_task(pump())
            try:
                async for event in self._service.ask(prompt, request_id):
                    self.AgentEvent(request_id, json.dumps(event.to_dict(), ensure_ascii=False))
            finally:
                pump_task.cancel()
                self._service.confirmations.detach_queue(queue)

        asyncio.run_coroutine_threadsafe(run(), self._loop)
        return request_id

    def Confirm(self, request_id: Str, approved: Bool) -> Bool:
        future = asyncio.run_coroutine_threadsafe(
            asyncio.to_thread(self._service.confirm, request_id, approved), self._loop
        )
        return bool(future.result(timeout=5))

    def ListTools(self) -> Str:
        return json.dumps(self._service.list_tools(), ensure_ascii=False)

    def Status(self) -> Str:
        return json.dumps(self._service.status(), ensure_ascii=False)

    @dbus_signal
    def AgentEvent(self, request_id: Str, payload_json: Str):
        pass


class DbusIpcServer(IpcServer):
    """Runs the GLib main loop for D-Bus in a thread; agent work stays on the
    asyncio loop."""

    def __init__(self, service: AgentService):
        self.service = service
        self._bus: SessionMessageBus | None = None
        self._glib_loop: EventLoop | None = None

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        interface = CoreInterface(self.service, loop)
        self._bus = SessionMessageBus()
        self._bus.publish_object(OBJECT_PATH, interface)
        self._bus.register_service(SERVICE_NAME)
        self._glib_loop = EventLoop()
        log.info("D-Bus IPC registered as %s", SERVICE_NAME)
        await asyncio.to_thread(self._glib_loop.run)

    async def shutdown(self) -> None:
        if self._glib_loop:
            self._glib_loop.quit()
        if self._bus:
            self._bus.disconnect()

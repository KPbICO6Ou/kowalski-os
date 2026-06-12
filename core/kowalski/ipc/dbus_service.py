"""D-Bus IPC: org.kowalski.Core on the session bus (Linux only, dasbus).

Methods:
  Ask(prompt: s) -> request_id: s     — events arrive as AgentEvent signals
  Confirm(request_id: s, approved: b) -> b
  ListTools() -> s (JSON)
  Status() -> s (JSON)
Signal:
  AgentEvent(request_id: s, payload_json: s)

Threading model: the GLib main loop runs in a worker thread (it dispatches
incoming D-Bus calls), the agent loop stays on the asyncio loop. Method
handlers therefore run on the GLib thread and must hand work to asyncio via
`run_coroutine_threadsafe`; signal emission is marshalled back onto the GLib
loop with `GLib.idle_add` so GDBus marshalling never races with the dispatcher.

Note: no `from __future__ import annotations` here — dasbus generates the
interface XML from the raw signature annotations, which must be real types,
not strings.
"""

import asyncio
import json
import logging
import uuid
from concurrent.futures import Future
from typing import Any

from dasbus.connection import SessionMessageBus
from dasbus.loop import EventLoop
from dasbus.server.interface import dbus_interface, dbus_signal
from dasbus.typing import Bool, Str
from gi.repository import GLib

from .base import AgentService, IpcServer

log = logging.getLogger(__name__)

SERVICE_NAME = "org.kowalski.Core"
OBJECT_PATH = "/org/kowalski/Core"


@dbus_interface(SERVICE_NAME)
class CoreInterface:
    """The published object. Public CamelCase members become D-Bus members."""

    def __init__(self, service: AgentService, loop: asyncio.AbstractEventLoop):
        self._service = service
        self._loop = loop
        # Keep strong references to in-flight ask futures so they are not
        # garbage-collected and their exceptions get logged.
        self._ask_futures: set[Future] = set()

    # -- D-Bus methods (called on the GLib thread) ---------------------------

    def Ask(self, prompt: Str) -> Str:
        request_id = uuid.uuid4().hex
        future = asyncio.run_coroutine_threadsafe(self._run_ask(prompt, request_id), self._loop)
        self._ask_futures.add(future)
        future.add_done_callback(self._ask_finished)
        return request_id

    def Confirm(self, request_id: Str, approved: Bool) -> Bool:
        # PendingQueueConfirmation.resolve is thread-safe: it hands the result
        # to the asyncio loop that owns the pending future.
        return bool(self._service.confirm(request_id, approved))

    def ListTools(self) -> Str:
        return json.dumps(self._service.list_tools(), ensure_ascii=False)

    def Status(self) -> Str:
        return json.dumps(self._service.status(), ensure_ascii=False)

    @dbus_signal
    def AgentEvent(self, request_id: Str, payload_json: Str):
        """One serialized AgentEvent per emission."""

    # -- internals ------------------------------------------------------------

    async def _run_ask(self, prompt: str, request_id: str) -> None:
        """Runs on the asyncio loop; streams agent events out as signals."""
        queue: asyncio.Queue = asyncio.Queue()
        self._service.confirmations.attach_queue(queue)

        async def pump_confirms() -> None:
            while True:
                event = await queue.get()
                self._emit(request_id, event.to_dict())

        pump = asyncio.create_task(pump_confirms())
        try:
            async for event in self._service.ask(prompt, request_id):
                self._emit(request_id, event.to_dict())
        except Exception as exc:  # surfaced to the client, not just the log
            log.exception("ask failed")
            self._emit(request_id, {"event": "ErrorEvent", "message": repr(exc)})
        finally:
            pump.cancel()
            self._service.confirmations.detach_queue(queue)

    def _emit(self, request_id: str, payload: dict[str, Any]) -> None:
        """Schedule signal emission on the GLib loop (callable from any thread)."""
        payload_json = json.dumps(payload, ensure_ascii=False)
        GLib.idle_add(self._emit_on_glib_thread, request_id, payload_json)

    def _emit_on_glib_thread(self, request_id: str, payload_json: str) -> bool:
        self.AgentEvent(request_id, payload_json)
        return GLib.SOURCE_REMOVE  # one-shot idle callback

    def _ask_finished(self, future: Future) -> None:
        self._ask_futures.discard(future)
        if not future.cancelled() and future.exception() is not None:
            log.error("ask task failed: %r", future.exception())


class DbusIpcServer(IpcServer):
    """Runs the GLib main loop for D-Bus in a thread; agent work stays on the
    asyncio loop."""

    def __init__(self, service: AgentService):
        self.service = service
        self._bus: SessionMessageBus | None = None
        self._glib_loop: EventLoop | None = None
        self._interface: CoreInterface | None = None

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        self._interface = CoreInterface(self.service, loop)
        self._bus = SessionMessageBus()
        self._bus.publish_object(OBJECT_PATH, self._interface)
        self._bus.register_service(SERVICE_NAME)
        glib_loop = EventLoop()
        self._glib_loop = glib_loop
        log.info("D-Bus IPC registered as %s", SERVICE_NAME)
        try:
            await asyncio.to_thread(glib_loop.run)
        finally:
            # Make sure the GLib thread can exit even if this task is
            # cancelled before shutdown() ran.
            glib_loop.quit()

    async def shutdown(self) -> None:
        if self._bus is not None:
            bus = self._bus
            self._bus = None
            try:
                # Unpublish the object and release the bus name while the
                # connection is still usable; these are sync D-Bus calls.
                await asyncio.to_thread(bus.disconnect)
            except Exception:
                log.exception("D-Bus disconnect failed")
        if self._glib_loop is not None:
            self._glib_loop.quit()
            self._glib_loop = None

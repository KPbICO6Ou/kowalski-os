"""Transport-agnostic IPC contract.

AgentService is the daemon-side facade the transports call into;
IpcServer is what a transport must implement."""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from ..agent.events import AgentEvent, ConfirmRequestEvent
from ..agent.loop import AgentLoop
from ..policy import ConfirmationProvider, ConfirmRequest
from ..tools.registry import ToolRegistry


class PendingQueueConfirmation(ConfirmationProvider):
    """Daemon-mode confirmations: emit an event over IPC, wait for confirm()
    with a timeout; timeout means deny."""

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._emit_queues: list[asyncio.Queue] = []

    def attach_queue(self, queue: asyncio.Queue) -> None:
        self._emit_queues.append(queue)

    def detach_queue(self, queue: asyncio.Queue) -> None:
        if queue in self._emit_queues:
            self._emit_queues.remove(queue)

    async def confirm(self, request: ConfirmRequest) -> bool:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[request.id] = future
        event = ConfirmRequestEvent(
            request_id=request.id,
            tool=request.tool,
            args=request.args,
            risk=str(request.risk),
            reason=request.reason,
        )
        for queue in self._emit_queues:
            queue.put_nowait(event)
        try:
            return await asyncio.wait_for(future, timeout=self.timeout)
        except TimeoutError:
            return False
        finally:
            self._pending.pop(request.id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        """Thread-safe: transports may call this from non-asyncio threads
        (e.g. the GLib loop of the D-Bus service), so the result is handed
        to the loop the future was created on in confirm()."""
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False

        def set_result() -> None:
            if not future.done():
                future.set_result(approved)

        future.get_loop().call_soon_threadsafe(set_result)
        return True


class AgentService:
    """Daemon-side facade shared by all transports (socket, D-Bus, REST)."""

    def __init__(
        self,
        loop_factory,  # () -> AgentLoop
        registry: ToolRegistry,
        confirmations: PendingQueueConfirmation,
    ):
        self._loop_factory = loop_factory
        self.registry = registry
        self.confirmations = confirmations

    async def ask(self, prompt: str, conversation_id: str | None = None) -> AsyncIterator[AgentEvent]:
        agent_loop: AgentLoop = self._loop_factory()
        conversation_id = conversation_id or uuid.uuid4().hex
        async for event in agent_loop.run(prompt, conversation_id=conversation_id):
            yield event

    def confirm(self, request_id: str, approved: bool) -> bool:
        return self.confirmations.resolve(request_id, approved)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk": str(t.risk),
                "inputSchema": t.input_schema,
            }
            for t in self.registry.list()
        ]

    def status(self) -> dict[str, Any]:
        from .. import __version__

        return {"version": __version__, "tools": len(self.registry.list())}


class IpcServer(ABC):
    @abstractmethod
    async def serve(self) -> None:
        """Run until cancelled."""

    @abstractmethod
    async def shutdown(self) -> None: ...

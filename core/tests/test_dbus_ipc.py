"""End-to-end D-Bus IPC test with a FakeLLM-backed AgentService.

Linux-only: needs a session bus (run inside docker/ubuntu-dev). The dasbus
client talks to the server over a private bus connection; AgentEvent signal
callbacks are dispatched by the server's GLib loop thread, so the test reads
them from a thread-safe queue via asyncio.to_thread."""

import asyncio
import json
import os
import queue
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pydantic import BaseModel

from kowalski.agent.llm import ToolCall
from kowalski.agent.loop import AgentLoop
from kowalski.ipc.base import AgentService, PendingQueueConfirmation
from kowalski.journal import ActionJournal
from kowalski.policy import SecurityPolicy
from kowalski.tools.base import RiskLevel, ToolDef, ToolResult
from kowalski.tools.registry import ToolRegistry

from .fake_llm import FakeLLM

_HAVE_SESSION_BUS = sys.platform.startswith("linux") and bool(
    os.environ.get("DBUS_SESSION_BUS_ADDRESS")
)

pytestmark = [
    pytest.mark.linux,
    pytest.mark.skipif(not _HAVE_SESSION_BUS, reason="needs Linux with a session D-Bus"),
]

SERVICE_NAME = "org.kowalski.Core"
OBJECT_PATH = "/org/kowalski/Core"


class WriteArgs(BaseModel):
    path: str


async def write_handler(args) -> ToolResult:
    return ToolResult(ok=True, content="written")


@pytest.fixture
async def dbus_server(tmp_path: Path, tmp_store):
    from kowalski.ipc.dbus_service import DbusIpcServer

    confirmations = PendingQueueConfirmation(timeout=10.0)
    registry = ToolRegistry(
        policy=SecurityPolicy(allowed_paths=[tmp_path / "allowed"]),
        journal=ActionJournal(tmp_store),
        confirmer=confirmations,
        tool_timeout=5.0,
    )
    registry.register(ToolDef(
        name="test.write", description="w", args_model=WriteArgs,
        risk=RiskLevel.WRITE, handler=write_handler, path_fields=("path",),
    ))
    # A home path is neither in the allowlist nor under a forbidden root -> CONFIRM.
    confirm_path = str(Path.home() / "kow-test-never-written.txt")
    llm = FakeLLM([
        [ToolCall(name="test.write", args={"path": confirm_path})],
        "All done.",
    ])
    service = AgentService(lambda: AgentLoop(llm, registry), registry, confirmations)
    server = DbusIpcServer(service)
    task = asyncio.create_task(server.serve())
    await _wait_for_name(SERVICE_NAME)
    yield server
    await server.shutdown()
    task.cancel()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)


@pytest.fixture
def client_bus():
    # A private connection, like an external client (GUI/CLI) would have.
    from dasbus.connection import AddressedMessageBus

    bus = AddressedMessageBus(os.environ["DBUS_SESSION_BUS_ADDRESS"])
    yield bus
    bus.connection.close_sync(None)


async def _wait_for_name(name: str, timeout: float = 5.0) -> None:
    from dasbus.connection import AddressedMessageBus

    bus = AddressedMessageBus(os.environ["DBUS_SESSION_BUS_ADDRESS"])
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if await asyncio.to_thread(bus.proxy.NameHasOwner, name):
                return
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"bus name {name} never appeared")
            await asyncio.sleep(0.05)
    finally:
        bus.connection.close_sync(None)


def _arg_types(member, direction: str | None) -> str:
    """Concatenated D-Bus types of <arg> children matching the direction."""
    return "".join(
        arg.get("type", "")
        for arg in member.findall("arg")
        if direction is None or arg.get("direction", "in") == direction
    )


async def test_introspection(dbus_server, client_bus):
    proxy = client_bus.get_proxy(
        SERVICE_NAME, OBJECT_PATH, interface_name="org.freedesktop.DBus.Introspectable"
    )
    xml = await asyncio.to_thread(proxy.Introspect)
    root = ET.fromstring(xml)
    iface = next(i for i in root.findall("interface") if i.get("name") == SERVICE_NAME)

    methods = {m.get("name"): m for m in iface.findall("method")}
    assert _arg_types(methods["Ask"], "in") == "s"
    assert _arg_types(methods["Ask"], "out") == "s"
    assert _arg_types(methods["Confirm"], "in") == "sb"
    assert _arg_types(methods["Confirm"], "out") == "b"
    assert _arg_types(methods["ListTools"], "out") == "s"
    assert _arg_types(methods["Status"], "out") == "s"

    signals = {s.get("name"): s for s in iface.findall("signal")}
    assert _arg_types(signals["AgentEvent"], None) == "ss"


async def test_status_and_tools(dbus_server, client_bus):
    proxy = client_bus.get_proxy(SERVICE_NAME, OBJECT_PATH, interface_name=SERVICE_NAME)
    status = json.loads(await asyncio.to_thread(proxy.Status))
    assert status["tools"] == 1
    tools = json.loads(await asyncio.to_thread(proxy.ListTools))
    assert tools[0]["name"] == "test.write"


async def test_ask_with_confirm_roundtrip(dbus_server, client_bus):
    """The write path is outside the allowlist -> ConfirmRequestEvent arrives
    as an AgentEvent signal; Confirm() approves it; the loop completes."""
    from dasbus.client.proxy import disconnect_proxy

    proxy = client_bus.get_proxy(SERVICE_NAME, OBJECT_PATH, interface_name=SERVICE_NAME)
    received: queue.Queue = queue.Queue()
    # Subscribe before Ask so no signal is missed. Callbacks fire on the
    # server's GLib thread -> hand them over through a thread-safe queue.
    await asyncio.to_thread(
        proxy.AgentEvent.connect,
        lambda rid, payload: received.put((rid, json.loads(payload))),
    )
    try:
        request_id = await asyncio.to_thread(proxy.Ask, "write the file")
        assert request_id

        events = []
        done = False
        while not done:
            rid, payload = await asyncio.to_thread(received.get, True, 10)
            if rid != request_id:
                continue
            events.append(payload)
            if payload.get("event") == "ConfirmRequestEvent":
                ok = await asyncio.to_thread(proxy.Confirm, payload["request_id"], True)
                assert ok is True
            if payload.get("event") in ("DoneEvent", "ErrorEvent"):
                done = True
    finally:
        disconnect_proxy(proxy)

    kinds = [e.get("event") for e in events]
    assert "ConfirmRequestEvent" in kinds
    assert "ToolResultEvent" in kinds
    assert kinds[-1] == "DoneEvent"
    tool_result = next(e for e in events if e.get("event") == "ToolResultEvent")
    assert tool_result["ok"] is True
    done_event = events[-1]
    assert "All done." in done_event["answer"]

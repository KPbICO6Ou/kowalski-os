"""AgentClient against the real SocketIpcServer + FakeLLM-backed AgentService.

Reuses the ``ipc`` / ``conv_ipc`` fixtures from test_socket_ipc.py so the client
is exercised against the genuine wire format, not a stand-in.
"""

from __future__ import annotations

import pytest

from kowalski.ipc.client import AgentClient, DaemonUnavailableError
from kowalski.ipc.socket_service import SocketIpcServer

from .test_socket_ipc import conv_ipc, ipc, short_sock_path  # noqa: F401  (fixtures)


async def test_status_and_tools(ipc: SocketIpcServer):  # noqa: F811
    client = AgentClient(ipc.socket_path)
    status = await client.status()
    assert status["tools"] == 1
    tools = await client.tools()
    assert [t["name"] for t in tools] == ["test.write"]


async def test_ask_stream_ends_in_done(conv_ipc):  # noqa: F811
    server, _llm = conv_ipc
    client = AgentClient(server.socket_path)
    events = [e async for e in client.ask("What is the capital of France?", "conv-1")]
    assert events[-1]["event"] == "DoneEvent"
    assert "Paris" in events[-1]["answer"]

    conversations = await client.conversations()
    assert [c["id"] for c in conversations] == ["conv-1"]


async def test_confirm_roundtrip_approves_write(ipc: SocketIpcServer):  # noqa: F811
    """A WRITE tool outside the allowlist -> ConfirmRequestEvent; approving it on
    a separate connection lets the tool run and yields a successful ToolResult."""
    client = AgentClient(ipc.socket_path)
    events = []
    async for event in client.ask("write the file"):
        events.append(event)
        if event.get("event") == "ConfirmRequestEvent":
            assert await client.confirm(event["request_id"], True) is True

    kinds = [e.get("event") for e in events]
    assert "ConfirmRequestEvent" in kinds
    assert kinds[-1] == "DoneEvent"
    tool_result = next(e for e in events if e.get("event") == "ToolResultEvent")
    assert tool_result["ok"] is True


async def test_daemon_unavailable_raises_clear_error(short_sock_path):  # noqa: F811
    client = AgentClient(short_sock_path)  # never bound
    with pytest.raises(DaemonUnavailableError) as excinfo:
        await client.status()
    message = str(excinfo.value)
    assert str(short_sock_path) in message
    assert "kow serve" in message

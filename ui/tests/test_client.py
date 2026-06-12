"""OmniClient against the fake daemon: streaming, ops, and failure modes."""

from __future__ import annotations

from pathlib import Path

import pytest

from kowui.client import DaemonUnavailableError, OmniClient

from .conftest import CONFIRM_SCRIPT


async def test_ask_streams_tokens_then_done(fake_daemon):
    async with OmniClient(fake_daemon.socket_path) as client:
        events = [e async for e in client.ask("hi", "conv1")]
    kinds = [e["event"] for e in events]
    assert kinds == ["TokenEvent", "TokenEvent", "DoneEvent"]
    assert "".join(e["text"] for e in events[:-1]) == "Hello, world"
    assert events[-1]["answer"] == "Hello, world"
    assert fake_daemon.asks == [{"op": "ask", "prompt": "hi", "conversation_id": "conv1"}]


async def test_ask_without_conversation_id_omits_field(fake_daemon):
    async with OmniClient(fake_daemon.socket_path) as client:
        [e async for e in client.ask("hi")]
    assert "conversation_id" not in fake_daemon.asks[0]


@pytest.mark.parametrize("fake_daemon", [CONFIRM_SCRIPT], indirect=True)
async def test_confirm_event_is_interleaved_in_stream(fake_daemon):
    async with OmniClient(fake_daemon.socket_path) as client:
        kinds = []
        async for event in client.ask("write it", "conv1"):
            kinds.append(event["event"])
            if event["event"] == "ConfirmRequestEvent":
                # separate connection, like the real protocol requires
                assert await client.confirm(event["request_id"], True) is True
    assert kinds == [
        "TokenEvent",
        "ToolCallEvent",
        "ConfirmRequestEvent",
        "ToolResultEvent",
        "DoneEvent",
    ]
    assert fake_daemon.confirms == [("req-1", True)]


async def test_status_and_tools(fake_daemon):
    async with OmniClient(fake_daemon.socket_path) as client:
        status = await client.status()
        tools = await client.tools()
    assert status["tools"] == 2
    assert [t["name"] for t in tools["tools"]] == ["fs.read", "fs.write"]


async def test_daemon_unavailable_raises_clear_error(short_sock_path):
    missing = Path(short_sock_path)  # never bound
    client = OmniClient(missing)
    with pytest.raises(DaemonUnavailableError) as excinfo:
        await client.status()
    message = str(excinfo.value)
    assert str(missing) in message
    assert "kow serve" in message


async def test_daemon_unavailable_on_ask(short_sock_path):
    client = OmniClient(short_sock_path)
    with pytest.raises(DaemonUnavailableError):
        async for _ in client.ask("hi"):
            pass
